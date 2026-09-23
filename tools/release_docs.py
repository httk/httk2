"""Prepare a selected batch's strict, versioned documentation inputs.

This helper deliberately has no release-ref operations.  It builds documentation
from disposable worktrees, copies only generated documentation inputs back, and
leaves the resulting module and aggregate changes for the caller to review.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from tools.release_batch import (
    Selection,
    _assert_source_unchanged,
    _manifest,
    _source_paths,
    environment,
    fingerprint,
    git,
    load_state,
    run,
    save_state,
    verify_code,
)
from tools.release_publish import print_release_groups


class DocsError(RuntimeError):
    """Raise when selected documentation cannot be prepared safely."""


def _copy_item(source: Path, destination: Path) -> None:
    """Copy one regular file or symlink, retaining its mode and link target."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


def _tracked_and_unignored(repo: Path) -> list[Path]:
    """Return present tracked and nonignored files without expanding ignored output."""

    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        return [
            path
            for path in repo.rglob("*")
            if (path.is_file() or path.is_symlink())
            and ".git" not in path.relative_to(repo).parts
            and path.relative_to(repo).as_posix()
            not in {
                "docs/_build",
                "docs/reference/autoapi",
                "docs/examples",
                "docs/_generated",
            }
            and not path.relative_to(repo)
            .as_posix()
            .startswith(
                (
                    "docs/_build/",
                    "docs/reference/autoapi/",
                    "docs/examples/",
                    "docs/_generated/",
                )
            )
        ]
    return [
        repo / name
        for name in result.stdout.decode().split("\0")
        if name and ((repo / name).exists() or (repo / name).is_symlink())
    ]


def _snapshot(repo: Path, destination: Path, *, omit_submodules: bool = False) -> None:
    """Copy the current meaningful worktree to *destination* without touching *repo*."""

    destination.mkdir(parents=True, exist_ok=True)
    for source in _tracked_and_unignored(repo):
        relative = source.relative_to(repo)
        if omit_submodules and relative.parts[0] == "submodules":
            continue
        _copy_item(source, destination / relative)


def _project(path: Path) -> dict[str, object]:
    """Read a project table from a pyproject file."""

    with (path / "pyproject.toml").open("rb") as stream:
        value = tomllib.load(stream).get("project")
    if not isinstance(value, dict):
        raise DocsError(f"{path}/pyproject.toml has no project table")
    return value


def _internal_dependencies(project: Path) -> list[tuple[str, str]]:
    """Read internal distribution/slugs in declared documentation order."""

    versioning = project / "docs" / "versioning.toml"
    if not versioning.is_file():
        return []
    with versioning.open("rb") as stream:
        value = tomllib.load(stream).get("internal-dependency", [])
    if not isinstance(value, list):
        raise DocsError(f"{versioning}: internal-dependency must be an array")
    result = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("distribution"), str)
            or not isinstance(item.get("slug"), str)
        ):
            raise DocsError(f"{versioning}: invalid internal dependency")
        result.append((item["distribution"], item["slug"]))
    return result


def _wheel(work: Path, selection: Selection) -> Path:
    """Find exactly one locally built wheel for a selected distribution."""

    normalized = selection.name.replace("-", "_")
    found = sorted((work / "wheels").glob(f"{normalized}-{selection.version}-*.whl"))
    if len(found) != 1:
        raise DocsError(
            f"expected one wheel for {selection.name} {selection.version}, found {len(found)}"
        )
    return found[0]


def _constraints(work: Path, selections: list[Selection]) -> Path:
    """Write the exact selected-distribution constraint file."""

    path = work / "batch-constraints.txt"
    path.write_text(
        "".join(f"{item.name}=={item.version}\n" for item in selections),
        encoding="utf-8",
    )
    return path


def _command(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
    """Run a logged command through the batch runner's common execution seam."""

    run(command, cwd, env, log)


def _venv(
    work: Path, name: str, core_wheel: Path, constraints: Path, logs: Path
) -> tuple[Path, dict[str, str]]:
    """Create an isolated Python 3.12 environment with the selected docs core."""

    root = work / "venvs" / name
    _command(
        ["uv", "venv", "--seed", "--python", "3.12", str(root)],
        work,
        os.environ.copy(),
        logs / f"{name}-venv.log",
    )
    python = root / "bin" / "python"
    env = environment(root)
    env.update(
        UV_FIND_LINKS=str(work / "wheels"),
        UV_CONSTRAINT=str(constraints),
        PIP_FIND_LINKS=str(work / "wheels"),
    )
    _command(
        [str(python), "-I", "-m", "pip", "install", "--no-deps", str(core_wheel)],
        work,
        env,
        logs / f"{name}-core.log",
    )
    return python, env


def _fetch_inventory(
    python: Path,
    source: str,
    destination: Path,
    project: str,
    version: str,
    cwd: Path,
    env: dict[str, str],
    log: Path,
) -> None:
    """Vendor a validated inventory using the existing core CLI."""

    _command(
        [
            str(python),
            "-I",
            "-m",
            "httk.core.docs",
            "fetch-inventory",
            source,
            str(destination),
            "--expect-project",
            project,
            "--expect-version",
            version,
        ],
        cwd,
        env,
        log,
    )


def _topological_candidates(selections: list[Selection]) -> list[Selection]:
    """Order candidate documentation builders after their candidate dependencies."""

    candidates = {item.name: item for item in selections if item.candidate}
    remaining = dict(candidates)
    ordered: list[Selection] = []
    while remaining:
        ready = [
            item
            for name, item in remaining.items()
            if all(
                distribution not in remaining
                for distribution, _slug in _internal_dependencies(item.repo)
            )
        ]
        if not ready:
            raise DocsError("cycle among candidate internal documentation dependencies")
        for item in sorted(ready, key=lambda value: value.name):
            ordered.append(item)
            del remaining[item.name]
    return ordered


def _locked_wheels(
    snapshot: Path, selections: list[Selection], work: Path, *, all_wheels: bool
) -> list[Path]:
    """Return local selected wheels that belong in this lock installation."""

    selected = {item.name.lower().replace("_", "-"): item for item in selections}
    names = (
        set(selected)
        if all_wheels
        else {
            match.group(1).lower().replace("_", "-")
            for line in (snapshot / "docs" / "requirements.lock")
            .read_text(encoding="utf-8")
            .splitlines()
            if (match := re.fullmatch(r"([A-Za-z0-9_.-]+)==[^\s#]+", line.strip()))
            is not None
        }
    )
    return [_wheel(work, selected[name]) for name in sorted(names & set(selected))]


def _install_locked(
    python: Path,
    snapshot: Path,
    selections: list[Selection],
    work: Path,
    env: dict[str, str],
    log_prefix: Path,
    *,
    all_wheels: bool = False,
) -> None:
    """Install one locked docs environment and force every internal wheel local."""

    lock = snapshot / "docs" / "requirements.lock"
    wheels = _locked_wheels(snapshot, selections, work, all_wheels=all_wheels)
    _command(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "-r",
            str(lock),
            "--constraint",
            env["UV_CONSTRAINT"],
            *map(str, wheels),
        ],
        snapshot,
        env,
        log_prefix.with_suffix(".lock.log"),
    )
    _command(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "-e",
            ".",
            "--no-deps",
            "--no-build-isolation",
        ],
        snapshot,
        env,
        log_prefix.with_suffix(".source.log"),
    )
    _command(
        [str(python), "-I", "-m", "pip", "check"],
        snapshot,
        env,
        log_prefix.with_suffix(".check.log"),
    )


def _candidate_snapshot(work: Path, selection: Selection) -> Path:
    """Create a disposable current-worktree snapshot for a candidate docs build."""

    target = work / "sources" / selection.name
    _snapshot(selection.repo, target)
    return target


def _cached_snapshot(
    entry: object, key: str, inventories: dict[str, str], repository: Path
) -> Path | None:
    """Return a reusable retained snapshot when its inputs still describe this build."""

    if not isinstance(entry, dict) or not isinstance(entry.get("snapshot"), str):
        return None
    if entry.get("inventories") != inventories or key not in {
        entry.get("key"),
        entry.get("final_key"),
    }:
        return None
    if not isinstance(entry.get("manifest"), dict) or not isinstance(
        entry.get("inventory_digest"), str
    ):
        return None
    path = Path(entry["snapshot"])
    inventory = path / "docs" / "_build" / "html" / "objects.inv"
    if (
        not inventory.is_file()
        or hashlib.sha256(inventory.read_bytes()).hexdigest()
        != entry["inventory_digest"]
    ):
        return None
    _assert_source_unchanged(repository, path, entry["manifest"])
    return path


def _cache_key(
    source: str, selections: list[Selection], inventories: dict[str, str], base_url: str
) -> str:
    """Hash every content and configuration input that makes a docs build reusable."""

    value = {
        "source": source,
        "batch": [(item.name, item.version, item.commit) for item in selections],
        "inventories": inventories,
        "base_url": base_url,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _candidate_docs(
    state: dict[str, object], selections: list[Selection], work: Path, base_url: str
) -> tuple[dict[str, dict[str, object]], bool]:
    """Build all candidate docs and return their cache records and copyback status."""

    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    constraints = _constraints(work, selections)
    core = next((item for item in selections if item.name == "httk-core"), None)
    if core is None:
        raise DocsError("selected batch does not include httk-core")
    tool_python, tool_env = _venv(
        work, "tooling", _wheel(work, core), constraints, logs
    )
    candidates = _topological_candidates(selections)
    records: dict[str, dict[str, object]] = {}
    built: dict[str, Path] = {}
    previous = state.get("docs", {})
    old_builds = previous.get("builds", {}) if isinstance(previous, dict) else {}
    changed = False
    by_name = {item.name: item for item in selections}
    for item in candidates:
        source_fingerprint = fingerprint(item.repo)
        snapshot = _candidate_snapshot(work, item)
        dependencies = _internal_dependencies(snapshot)
        inventory_hashes: dict[str, str] = {}
        for distribution, slug in dependencies:
            dependency = by_name.get(distribution)
            if dependency is None:
                raise DocsError(
                    f"{item.name}: unknown selected internal dependency {distribution}"
                )
            destination = snapshot / "docs" / "_inventories" / f"{slug}.inv"
            if dependency.candidate:
                source = built.get(distribution)
                if source is None:
                    raise DocsError(
                        f"{item.name}: candidate inventory {distribution} was not built first"
                    )
                _fetch_inventory(
                    tool_python,
                    source.as_uri(),
                    destination,
                    slug,
                    dependency.version,
                    snapshot,
                    tool_env,
                    logs / f"{item.name}-{slug}-inventory.log",
                )
            else:
                url = f"{base_url.rstrip('/')}/{slug}/v{dependency.version}/objects.inv"
                _fetch_inventory(
                    tool_python,
                    url,
                    destination,
                    slug,
                    dependency.version,
                    snapshot,
                    tool_env,
                    logs / f"{item.name}-{slug}-inventory.log",
                )
            inventory_hashes[slug] = hashlib.sha256(
                destination.read_bytes()
            ).hexdigest()
        cache_key = _cache_key(
            source_fingerprint, selections, inventory_hashes, base_url
        )
        old = old_builds.get(item.name) if isinstance(old_builds, dict) else None
        cache = _cached_snapshot(old, cache_key, inventory_hashes, item.repo)
        if cache is not None:
            shutil.rmtree(snapshot)
            shutil.copytree(cache, snapshot, symlinks=True)
        else:
            _command(
                [str(tool_python), "-I", "-m", "httk.core.docs", "lock", str(snapshot)],
                snapshot,
                tool_env,
                logs / f"{item.name}-lock.log",
            )
            source_manifest = _manifest(snapshot, _source_paths(snapshot))
            docs_python, docs_env = _venv(
                work, f"{item.name}-docs", _wheel(work, core), constraints, logs
            )
            _install_locked(
                docs_python, snapshot, selections, work, docs_env, logs / item.name
            )
            _command(
                [
                    str(docs_python),
                    "-I",
                    "-m",
                    "httk.core.docs",
                    "check-release",
                    "--tag",
                    f"v{item.version}",
                ],
                snapshot,
                docs_env,
                logs / f"{item.name}-release.log",
            )
            build_env = dict(
                docs_env,
                HTTK_DOCS_VERSION=f"v{item.version}",
                HTTK_DOCS_BASE_URL=base_url,
            )
            _command(
                ["make", "docs", f"PYTHON={docs_python}", f"DOCS_BASE_URL={base_url}"],
                snapshot,
                build_env,
                logs / f"{item.name}-sphinx.log",
            )
            _assert_source_unchanged(item.repo, snapshot, source_manifest)
        if cache is not None:
            source_manifest = old["manifest"]
        inventory = snapshot / "docs" / "_build" / "html" / "objects.inv"
        if not inventory.is_file():
            raise DocsError(
                f"{item.name}: strict docs build did not produce objects.inv"
            )
        built[item.name] = inventory
        records[item.name] = {
            "key": cache_key,
            "source": source_fingerprint,
            "snapshot": str(snapshot),
            "inventories": inventory_hashes,
            "manifest": source_manifest,
            "inventory_digest": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        }
    for item in candidates:
        before = fingerprint(item.repo)
        if before != records[item.name]["source"]:
            raise DocsError(
                f"{item.name}: working tree changed during docs preparation; no inputs copied back"
            )
    for item in candidates:
        snapshot = Path(str(records[item.name]["snapshot"]))
        for relative in [
            Path("docs/requirements.lock"),
            *sorted(
                path.relative_to(snapshot)
                for path in (snapshot / "docs" / "_inventories").glob("*.inv")
            ),
        ]:
            source = snapshot / relative
            target = item.repo / relative
            if not target.exists() or target.read_bytes() != source.read_bytes():
                changed = True
            _copy_item(source, target)
        final_fingerprint = fingerprint(item.repo)
        records[item.name]["final"] = final_fingerprint
        records[item.name]["final_key"] = _cache_key(
            final_fingerprint, selections, records[item.name]["inventories"], base_url
        )
    return records, changed


def _clean(repo: Path) -> bool:
    """Return whether a repository has no worktree or index changes."""

    return not git(repo, "status", "--porcelain")


def _overlay_site(source: Path, destination: Path) -> None:
    """Overlay real top-site edits on a disposable clone without touching submodules."""

    _snapshot(source, destination, omit_submodules=True)
    tracked = (
        subprocess.run(
            ["git", "ls-files", "-z"], cwd=source, capture_output=True, check=True
        )
        .stdout.decode()
        .split("\0")
    )
    for relative in tracked:
        if (
            relative
            and not relative.startswith("submodules/")
            and not (source / relative).exists()
            and not (source / relative).is_symlink()
        ):
            target = destination / relative
            if target.exists() or target.is_symlink():
                target.unlink()


def _aggregate(
    state: dict[str, object],
    selections: list[Selection],
    work: Path,
    site: Path,
    base_url: str,
) -> dict[str, object]:
    """Build aggregate docs in a disposable clone and copy only its generated inputs back."""

    if git(site, "branch", "--show-current") != "main":
        raise DocsError(f"{site}: aggregate docs must be prepared on main")
    if any(item.candidate and not _clean(item.repo) for item in selections):
        raise DocsError(
            "candidate documentation inputs are uncommitted; commit/push modules then run release-aggregate-docs-build"
        )
    members = [
        item
        for item in selections
        if subprocess.run(
            ["git", "ls-files", "--error-unmatch", f"submodules/{item.name}"],
            cwd=site,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    ]
    final = [
        Selection(
            item.name,
            item.repo,
            git(item.repo, "rev-parse", "HEAD") if item.candidate else item.commit,
            item.version,
            item.candidate,
            item.tag,
        )
        for item in members
    ]
    for item in final:
        child = site / "submodules" / item.name
        if child.exists() and not _clean(child):
            raise DocsError(f"{child}: refusing to overwrite dirty submodule checkout")
    original = fingerprint(site)
    scratch = work / "aggregate"
    _command(
        ["git", "clone", "--no-local", str(site), str(scratch)],
        work,
        os.environ.copy(),
        work / "logs" / "site-clone.log",
    )
    _overlay_site(site, scratch)
    for item in final:
        child = scratch / "submodules" / item.name
        if child.exists():
            shutil.rmtree(child)
        _command(
            ["git", "clone", "--no-local", str(item.repo), str(child)],
            scratch,
            os.environ.copy(),
            work / "logs" / f"site-{item.name}-clone.log",
        )
        _command(
            ["git", "checkout", "--detach", item.commit],
            child,
            os.environ.copy(),
            work / "logs" / f"site-{item.name}-checkout.log",
        )
        tag = f"v{item.version}"
        if subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            cwd=child,
            capture_output=True,
            check=False,
        ).returncode:
            _command(
                ["git", "-c", "tag.gpgSign=false", "tag", tag, item.commit],
                child,
                os.environ.copy(),
                work / "logs" / f"site-{item.name}-tag.log",
            )
        _command(
            ["git", "add", f"submodules/{item.name}"],
            scratch,
            os.environ.copy(),
            work / "logs" / f"site-{item.name}-gitlink.log",
        )
    constraints = _constraints(work, final)
    core = next(item for item in final if item.name == "httk-core")
    tool_python, tool_env = _venv(
        work, "site-tooling", _wheel(work, core), constraints, work / "logs"
    )
    _command(
        ["make", "ecosystem-manifest-release"],
        scratch,
        tool_env,
        work / "logs" / "site-manifest.log",
    )
    _command(
        [str(tool_python), "-I", "-m", "httk.core.docs", "lock", str(scratch)],
        scratch,
        tool_env,
        work / "logs" / "site-lock.log",
    )
    source_fingerprint = fingerprint(scratch)
    _command(
        [str(tool_python), "-I", "scripts/check_lock_members.py"],
        scratch,
        tool_env,
        work / "logs" / "site-members.log",
    )
    _command(
        [str(tool_python), "-I", "scripts/verify_topology.py"],
        scratch,
        tool_env,
        work / "logs" / "site-topology.log",
    )
    docs_python, docs_env = _venv(
        work, "site-docs", _wheel(work, core), constraints, work / "logs"
    )
    _install_locked(
        docs_python,
        scratch,
        final,
        work,
        docs_env,
        work / "logs" / "site",
        all_wheels=True,
    )
    _command(
        [
            "make",
            "first-use-check",
            f"PYTHON={docs_python}",
            f"DOCS_BASE_URL={base_url}",
        ],
        scratch,
        docs_env,
        work / "logs" / "site-first-use.log",
    )
    version = str(_project(scratch)["version"])
    _command(
        ["make", "docs-full", f"PYTHON={docs_python}", f"DOCS_BASE_URL={base_url}"],
        scratch,
        dict(docs_env, HTTK_DOCS_VERSION=f"v{version}", HTTK_DOCS_BASE_URL=base_url),
        work / "logs" / "site-sphinx.log",
    )
    if fingerprint(scratch) != source_fingerprint:
        raise DocsError(
            "aggregate documentation gates changed tracked source; no inputs copied back"
        )
    if fingerprint(site) != original:
        raise DocsError(
            f"{site}: working tree changed during aggregate preparation; no inputs copied back"
        )
    for relative in (Path("docs/requirements.lock"), Path("docs/ecosystem.json")):
        _copy_item(scratch / relative, site / relative)
    for item in final:
        child = site / "submodules" / item.name
        _command(
            ["git", "fetch", str(item.repo), item.commit],
            child,
            os.environ.copy(),
            work / "logs" / f"real-{item.name}-fetch.log",
        )
        _command(
            ["git", "checkout", "--detach", item.commit],
            child,
            os.environ.copy(),
            work / "logs" / f"real-{item.name}-checkout.log",
        )
    return {
        "repo": str(site),
        "fingerprint": fingerprint(site),
        "heads": {item.name: item.commit for item in final},
    }


def _print_groups(selections: list[Selection]) -> None:
    """Print the manual publication order after documentation is prepared."""

    print_release_groups(selections)


def build_docs(state_path: Path, base_url: str = "https://docs.httk.org") -> None:
    """Prepare module documentation, leaving verified inputs for manual commits.

    :param state_path: Retained successful batch-code report.
    :param base_url: Public documentation URL for final release cross-links.
    :raises DocsError: If a module's documentation or its code evidence fails.
    """
    state = load_state(state_path)
    docs = state.get("docs")
    if not isinstance(docs, dict):
        docs = {}
    docs.update(status="checking", modules_status="checking")
    docs.pop("site", None)
    state["docs"] = docs
    save_state(state_path, state)
    work = Path(tempfile.mkdtemp(prefix="httk-release-docs-"))
    try:
        selections = verify_code(state)
        wheelhouse = Path(str(state.get("wheels", ""))).resolve()
        if not wheelhouse.is_dir():
            raise DocsError("batch report does not retain selected wheels")
        (work / "wheels").symlink_to(wheelhouse)
        records, _changed = _candidate_docs(state, selections, work, base_url)
        docs.update(
            builds=records,
            fingerprints={name: entry["final"] for name, entry in records.items()},
            modules_status="passed",
            status="modules-ready",
            base_url=base_url,
            work=str(work),
        )
        save_state(state_path, state)
        print(
            "Module documentation passed. Review, commit and push module changes, "
            "then run make release-aggregate-docs-build."
        )
        _print_groups(selections)
    except BaseException:
        docs.update(status="failed", modules_status="failed", work=str(work))
        save_state(state_path, state)
        raise


def build_aggregate_docs(
    state_path: Path, site: Path, base_url: str = "https://docs.httk.org"
) -> None:
    """Prepare aggregate docs after the verified module inputs are committed.

    :param state_path: Retained successful code and module-documentation report.
    :param site: Aggregate documentation repository on main.
    :param base_url: Same public URL used by the module-documentation stage.
    :raises DocsError: If module evidence changed or aggregate validation fails.
    """
    state = load_state(state_path)
    docs = state.get("docs")
    if not isinstance(docs, dict) or docs.get("modules_status") != "passed":
        raise DocsError("run make release-docs-build successfully first")
    docs["status"] = "aggregate-checking"
    docs.pop("site", None)
    save_state(state_path, state)
    work = Path(tempfile.mkdtemp(prefix="httk-release-aggregate-docs-"))
    try:
        selections = verify_code(state)
        if docs.get("base_url") != base_url:
            raise DocsError(
                "documentation base URL changed; rerun make release-docs-build"
            )
        for item in selections:
            if not item.candidate:
                continue
            if docs.get("fingerprints", {}).get(item.name) != fingerprint(item.repo):
                raise DocsError(
                    f"{item.name}: module docs changed; rerun make release-docs-build"
                )
            if not _clean(item.repo):
                raise DocsError(
                    f"{item.name}: commit module documentation before aggregate preparation"
                )
        wheelhouse = Path(str(state.get("wheels", ""))).resolve()
        if not wheelhouse.is_dir():
            raise DocsError("batch report does not retain selected wheels")
        (work / "wheels").symlink_to(wheelhouse)
        (work / "logs").mkdir()
        docs["site"] = _aggregate(state, selections, work, site, base_url)
        docs.update(status="passed", aggregate_work=str(work))
        save_state(state_path, state)
        print(
            "Aggregate documentation passed. Review, commit and push the aggregate "
            "inputs and gitlinks, then run make release-merge-tag-and-push-main."
        )
        _print_groups(selections)
    except BaseException:
        docs.update(status="aggregate-failed", aggregate_work=str(work))
        save_state(state_path, state)
        raise
