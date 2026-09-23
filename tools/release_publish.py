"""Safely fast-forward verified release candidates and publish their tags."""

import re
import subprocess
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tools.release_batch import (
    Selection,
    fingerprint,
    git,
    load_state,
    save_state,
    verify_code,
)


class PublicationError(RuntimeError):
    """Raised when release publication evidence is unsafe or incomplete."""


@dataclass(frozen=True)
class PublicationPlan:
    """Fully preflighted publication operation for one candidate."""

    selection: Selection
    head: str
    remote_main: str
    remote_tag: str | None


_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_ZERO_OID = "0" * 40


def _normalise_name(name: str) -> str:
    """Return the comparison form used by Python distribution names."""

    return re.sub(r"[-_.]+", "-", name).lower()


def _git_optional(repo: Path, *args: str) -> str | None:
    """Run Git and return output, or ``None`` for an absent optional object."""

    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _remote_ref(repo: Path, ref: str) -> str | None:
    """Read one remote reference without changing any local reference."""

    output = git(repo, "ls-remote", "origin", ref)
    for line in output.splitlines():
        oid, found = line.split(maxsplit=1)
        if found == ref:
            return oid
    return None


def _remote_tag_commit(repo: Path, tag: str) -> str | None:
    """Return the commit denoted by a remote lightweight or annotated tag."""

    return _remote_ref(repo, f"refs/tags/{tag}^{{}}") or _remote_ref(
        repo, f"refs/tags/{tag}"
    )


def _tag_object(repo: Path, tag: str) -> str | None:
    """Return a local tag reference's unpeeled object ID, if present."""

    return _git_optional(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")


def _local_tag_commit(repo: Path, tag: str) -> str | None:
    """Return the commit denoted by a local tag, if it exists."""

    return _git_optional(repo, "rev-parse", "--verify", "--quiet", f"{tag}^{{}}")


def _verified_signed_tag(repo: Path, object_id: str, description: str) -> None:
    """Require a tag object with a Git-verifiable signature.

    :raises PublicationError: If a lightweight, unsigned, or unverifiable tag
        is encountered.
    """

    if git(repo, "cat-file", "-t", object_id) != "tag":
        raise PublicationError(
            f"{description}: final tag must be an annotated signed tag"
        )
    try:
        git(repo, "verify-tag", object_id)
    except subprocess.CalledProcessError as error:
        raise PublicationError(
            f"{description}: final tag signature does not verify"
        ) from error


def _preflight_final_tags(
    repo: Path, tag: str, head: str, remote_tag: str | None
) -> None:
    """Reject any pre-existing final tag that is not signed and exact."""

    local_object = _tag_object(repo, tag)
    remote_object = _remote_ref(repo, f"refs/tags/{tag}")
    for location, commit in (
        ("local", _local_tag_commit(repo, tag)),
        ("remote", remote_tag),
    ):
        if commit is not None and commit != head:
            raise PublicationError(
                f"{repo.name}: {location} final tag {tag} has another commit"
            )
    if (
        remote_object is not None
        and _git_optional(repo, "cat-file", "-e", remote_object) is None
    ):
        # Fetch only FETCH_HEAD/object data: never create or replace a local tag ref.
        git(repo, "fetch", "--no-tags", "origin", f"refs/tags/{tag}")
    for location, object_id in (("local", local_object), ("remote", remote_object)):
        if object_id is not None:
            _verified_signed_tag(repo, object_id, f"{repo.name}: {location}")


def _clean(repo: Path, description: str) -> None:
    """Require no tracked, untracked, or dirty-submodule content."""

    if git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ):
        raise PublicationError(f"{description}: worktree is not clean")


def _ancestor(repo: Path, older: str, newer: str, message: str) -> None:
    """Require ``older`` to be an ancestor of ``newer``."""

    if _git_optional(repo, "merge-base", "--is-ancestor", older, newer) is None:
        raise PublicationError(message)


def _ensure_remote_main_object(repo: Path, remote_main: str) -> None:
    """Make a checked remote-main object available for ancestry verification."""

    if _git_optional(repo, "cat-file", "-e", f"{remote_main}^{{commit}}") is not None:
        return
    git(
        repo, "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main"
    )
    fetched = _git_optional(repo, "rev-parse", "refs/remotes/origin/main")
    if fetched != remote_main:
        raise PublicationError(f"{repo.name}: origin/main changed while preflighting")


def _main_worktree_checked_out(repo: Path) -> bool:
    """Return whether another linked worktree has ``main`` checked out."""

    here = repo.resolve()
    worktree: Path | None = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            worktree = Path(line.removeprefix("worktree ")).resolve()
        elif line == "branch refs/heads/main" and worktree != here:
            return True
    return False


def _docs_evidence(
    state: dict[object, object], selections: list[Selection]
) -> tuple[Path, dict[str, str]]:
    """Validate and return the completed aggregate documentation evidence."""

    docs = state.get("docs")
    if not isinstance(docs, dict) or docs.get("status") != "passed":
        raise PublicationError("documentation gate has not passed")
    fingerprints = docs.get("fingerprints")
    site = docs.get("site")
    if not isinstance(fingerprints, dict) or not isinstance(site, dict):
        raise PublicationError("documentation evidence is malformed")
    candidates = [selection for selection in selections if selection.candidate]
    expected_names = {selection.name for selection in candidates}
    if set(fingerprints) != expected_names:
        raise PublicationError(
            "documentation fingerprints do not cover exactly the candidates"
        )
    for selection in candidates:
        if fingerprints.get(selection.name) != fingerprint(selection.repo):
            raise PublicationError(
                f"{selection.name}: documentation fingerprint is stale"
            )
    repository = site.get("repo")
    if not isinstance(repository, str):
        raise PublicationError("documentation site repository is missing")
    heads = site.get("heads")
    if not isinstance(heads, dict) or not all(
        isinstance(name, str) and isinstance(commit, str)
        for name, commit in heads.items()
    ):
        raise PublicationError("documentation site gitlink evidence is malformed")
    return Path(repository), heads


def _site_gitlinks(site: Path) -> dict[str, str]:
    """Return the committed aggregate submodule names and their exact commits."""

    gitlinks: dict[str, str] = {}
    for line in git(site, "ls-files", "--stage").splitlines():
        metadata, path = line.split("\t", 1)
        if metadata.startswith("160000 "):
            prefix, separator, name = path.partition("submodules/")
            if prefix or not separator or "/" in name:
                raise PublicationError(
                    f"documentation site has unsupported gitlink {path}"
                )
            gitlinks[name] = metadata.split()[1]
    configured = {
        line.split(maxsplit=1)[1]
        for line in git(
            site,
            "config",
            "-f",
            ".gitmodules",
            "--get-regexp",
            r"^submodule\..*\.path$",
        ).splitlines()
        if len(line.split(maxsplit=1)) == 2
    }
    if configured != {f"submodules/{name}" for name in gitlinks}:
        raise PublicationError(
            "documentation site submodule configuration differs from gitlinks"
        )
    return gitlinks


def _preflight_site(
    site: Path,
    site_fingerprint: object,
    heads: dict[str, str],
    selections: list[Selection],
) -> None:
    """Verify the already-committed aggregate documentation snapshot."""

    if not isinstance(site_fingerprint, str):
        raise PublicationError("documentation site fingerprint is missing")
    _clean(site, "documentation site")
    if fingerprint(site) != site_fingerprint:
        raise PublicationError("documentation site fingerprint is stale")
    head = git(site, "rev-parse", "HEAD")
    remote_main = _remote_ref(site, "refs/heads/main")
    if remote_main is None or head != remote_main:
        raise PublicationError("documentation site HEAD does not equal origin/main")

    selected = {
        selection.name: (
            git(selection.repo, "rev-parse", "develop")
            if selection.candidate
            else selection.commit
        )
        for selection in selections
    }
    gitlinks = _site_gitlinks(site)
    if set(heads) != set(gitlinks):
        raise PublicationError(
            "documentation site heads do not cover exactly its aggregate members"
        )
    for name, commit in heads.items():
        if name not in selected or selected[name] != commit:
            raise PublicationError(
                f"{name}: documentation head is not the selected commit"
            )
        if gitlinks[name] != commit:
            raise PublicationError(
                f"{name}: documentation gitlink differs from its recorded head"
            )


def _preflight_candidate(selection: Selection) -> PublicationPlan:
    """Verify every condition needed before mutating one candidate repository."""

    repo = selection.repo
    _clean(repo, selection.name)
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "develop":
        raise PublicationError(f"{selection.name}: develop is not checked out")
    head = git(repo, "rev-parse", "HEAD")
    remote_develop = _remote_ref(repo, "refs/heads/develop")
    if remote_develop != head:
        raise PublicationError(f"{selection.name}: develop differs from origin/develop")
    remote_main = _remote_ref(repo, "refs/heads/main")
    if remote_main is None:
        raise PublicationError(f"{selection.name}: origin/main is absent")
    _ensure_remote_main_object(repo, remote_main)
    _ancestor(
        repo,
        remote_main,
        head,
        f"{selection.name}: origin/main cannot fast-forward to develop",
    )
    if _local_tag_commit(repo, selection.tag) is None:
        raise PublicationError(f"{selection.name}: missing rc0 tag {selection.tag}")
    _ancestor(
        repo,
        selection.tag,
        head,
        f"{selection.name}: rc0 tag is not an ancestor of develop",
    )

    remote_tag = _remote_tag_commit(repo, f"v{selection.version}")
    _preflight_final_tags(repo, f"v{selection.version}", head, remote_tag)
    if _main_worktree_checked_out(repo):
        raise PublicationError(
            f"{selection.name}: main is checked out in another worktree"
        )
    local_main = _git_optional(
        repo, "rev-parse", "--verify", "--quiet", "refs/heads/main"
    )
    if local_main is not None:
        _ancestor(
            repo,
            local_main,
            head,
            f"{selection.name}: local main cannot fast-forward to develop",
        )
    return PublicationPlan(selection, head, remote_main, remote_tag)


def _publish_one(plan: PublicationPlan, user_name: str, user_email: str) -> None:
    """Publish a preflighted candidate without rewriting refs or tags."""

    selection = plan.selection
    repo = selection.repo
    final_tag = f"v{selection.version}"
    head = plan.head
    if plan.remote_main == head and plan.remote_tag == head:
        print(f"== {selection.name}: {final_tag} already published")
        return

    old_main = _git_optional(
        repo, "rev-parse", "--verify", "--quiet", "refs/heads/main"
    )
    git(repo, "update-ref", "refs/heads/main", head, old_main or _ZERO_OID)
    local_tag = _local_tag_commit(repo, final_tag)
    if local_tag is None:
        git(
            repo,
            "-c",
            f"user.name={user_name}",
            "-c",
            f"user.email={user_email}",
            "tag",
            "-s",
            "-m",
            final_tag,
            final_tag,
            head,
        )

    refs = ["refs/heads/main:refs/heads/main"]
    if plan.remote_tag is None:
        refs.append(f"refs/tags/{final_tag}:refs/tags/{final_tag}")
    git(repo, "push", "--atomic", "origin", *refs)
    print(f"== {selection.name}: published {final_tag}")


def _toml_at(repo: Path, commit: str, path: str) -> dict[str, object] | None:
    """Load a TOML file from the selected commit when it exists."""

    content = _git_optional(repo, "show", f"{commit}:{path}")
    return None if content is None else tomllib.loads(content)


def _requirement_names(value: object) -> set[str]:
    """Extract conservative requirement-name candidates from TOML values."""

    found: set[str] = set()
    if isinstance(value, str):
        match = _REQUIREMENT_NAME.match(value)
        if match:
            found.add(_normalise_name(match.group(1)))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_requirement_names(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_requirement_names(item))
    return found


def _versioning_requirements(value: object) -> set[str]:
    """Extract only declared internal dependencies from versioning metadata."""

    if not isinstance(value, dict):
        return set()
    names: set[str] = set()
    for key, item in value.items():
        if _normalise_name(key) in {"internal-dependency", "internal-dependencies"}:
            names.update(_requirement_names(item))
        elif isinstance(item, dict):
            names.update(_versioning_requirements(item))
    return names


def release_groups(selections: Iterable[Selection]) -> list[list[str]]:
    """Return candidates in dependency-ordered publication groups.

    All optional dependency groups and documentation-versioning TOML values are
    considered deliberately: releasing an extra must not outrun an internal
    dependency merely because ordinary runtime installation does not use it.
    """

    selected = list(selections)
    projects: dict[str, Selection] = {}
    for selection in selected:
        project = _toml_at(selection.repo, selection.commit, "pyproject.toml")
        if not isinstance(project, dict) or not isinstance(
            project.get("project"), dict
        ):
            raise PublicationError(
                f"{selection.name}: pyproject.toml is missing project metadata"
            )
        name = project["project"].get("name")
        if not isinstance(name, str):
            raise PublicationError(f"{selection.name}: project.name is missing")
        normalised = _normalise_name(name)
        if normalised in projects:
            raise PublicationError(f"duplicate selected distribution {name}")
        projects[normalised] = selection

    candidates = {
        selection.name: selection for selection in selected if selection.candidate
    }
    dependencies = {name: set() for name in candidates}
    for selection in selected:
        project = _toml_at(selection.repo, selection.commit, "pyproject.toml")
        assert project is not None
        metadata = project.get("project", {})
        assert isinstance(metadata, dict)
        requirement_names = _requirement_names(metadata.get("dependencies", []))
        requirement_names.update(
            _requirement_names(metadata.get("optional-dependencies", {}))
        )
        build_system = project.get("build-system", {})
        if isinstance(build_system, dict):
            requirement_names.update(
                _requirement_names(build_system.get("requires", []))
            )
        versioning = _toml_at(selection.repo, selection.commit, "docs/versioning.toml")
        if versioning is not None:
            requirement_names.update(_versioning_requirements(versioning))
        if selection.candidate:
            # The final docs lock also pins transitive batch dependencies. Its
            # clean GitHub install needs those versions published beforehand.
            lock = selection.repo / "docs/requirements.lock"
            if lock.is_file():
                requirement_names.update(
                    _requirement_names(lock.read_text().splitlines())
                )
            for requirement in requirement_names:
                dependency = projects.get(requirement)
                if (
                    dependency is not None
                    and dependency.candidate
                    and dependency.name != selection.name
                ):
                    dependencies[selection.name].add(dependency.name)

    groups: list[list[str]] = []
    remaining = {name: set(required) for name, required in dependencies.items()}
    while remaining:
        ready = sorted(name for name, required in remaining.items() if not required)
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise PublicationError(f"release dependency cycle: {cycle}")
        groups.append(ready)
        for name in ready:
            del remaining[name]
        finished = set(ready)
        for required in remaining.values():
            required.difference_update(finished)
    return groups


def print_release_groups(selections: Iterable[Selection]) -> None:
    """Print final candidate tags in dependency-ordered release groups."""

    selected = {selection.name: selection for selection in selections}
    for number, group in enumerate(release_groups(selected.values()), 1):
        print(f"== Group {number}")
        for name in group:
            print(f"   {name}: v{selected[name].version}")
        print("   Wait for PyPI and versioned documentation before the next group.")


def publish(state_path: Path, user_name: str, user_email: str) -> None:
    """Preflight then publish all verified candidates with final signed tags.

    :param state_path: Saved batch-release state.
    :param user_name: Git identity name used for final tag signatures.
    :param user_email: Git identity email used for final tag signatures.
    :raises PublicationError: If any precondition is unsafe or incomplete.
    """

    state = load_state(state_path)
    selections = verify_code(state)
    groups = release_groups(selections)
    site, heads = _docs_evidence(state, selections)
    docs = state["docs"]
    assert isinstance(docs, dict)
    site_record = docs["site"]
    assert isinstance(site_record, dict)
    _preflight_site(site, site_record.get("fingerprint"), heads, selections)
    plans = [
        _preflight_candidate(selection)
        for selection in selections
        if selection.candidate
    ]
    progress = state.setdefault("publication", {})
    if not isinstance(progress, dict):
        raise PublicationError("publication progress is malformed")
    for group in groups:
        for name in group:
            plan = next(plan for plan in plans if plan.selection.name == name)
            _publish_one(plan, user_name, user_email)
            progress[name] = {"commit": plan.head, "tag": f"v{plan.selection.version}"}
            save_state(state_path, state)
    print_release_groups(selections)
