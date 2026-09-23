"""Select and verify an isolated, commit-pinned runtime release batch."""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

PYTHONS = ("3.12", "3.13", "3.14")
_RC = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-rc0$")
_STABLE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class Selection:
    """One exact module revision selected for a release batch."""

    name: str
    repo: Path
    commit: str
    version: str
    candidate: bool
    tag: str


def git(repo: Path, *args: str) -> str:
    """Run a checked Git command in *repo* and return its standard output.

    :raises subprocess.CalledProcessError: If Git rejects the command.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result.stdout.strip()


def _has_ref(repo: Path, ref: str) -> bool:
    """Return whether *ref* resolves in *repo*."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _tags(repo: Path) -> dict[str, str]:
    """Map local tag names to their peeled commit IDs."""
    result = {}
    for tag in git(
        repo, "for-each-ref", "--format=%(refname:short)", "refs/tags"
    ).splitlines():
        if tag:
            result[tag] = git(repo, "rev-parse", f"{tag}^{{}}")
    return result


def _project_version(repo: Path, commit: str) -> str:
    """Read the project version from *commit*."""
    try:
        project = tomllib.loads(git(repo, "show", f"{commit}:pyproject.toml"))[
            "project"
        ]
        return str(project["version"])
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{repo}: {commit} has no usable project.version") from exc


def _candidate(name: str, repo: Path) -> Selection | None:
    """Return the active rc0 selection for *repo*, if there is one."""
    if not _has_ref(repo, "develop"):
        return None
    develop = git(repo, "rev-parse", "develop")
    tags = _tags(repo)
    candidates = sorted(
        tag for tag, commit in tags.items() if commit == develop and _RC.fullmatch(tag)
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError(
            f"{name}: develop has multiple rc0 tags: {', '.join(candidates)}"
        )
    tag = candidates[0]
    version = _project_version(repo, develop)
    if tag != f"v{version}-rc0":
        raise ValueError(
            f"{name}: {tag} does not match develop pyproject.toml version {version}"
        )
    final = f"v{version}"
    if final in tags:
        if tags[final] == develop:
            return None  # A finalised rc0 is history, not a new candidate.
        raise ValueError(
            f"{name}: final tag {final} already exists at {tags[final]}, not develop"
        )
    if git(repo, "branch", "--show-current") != "develop":
        raise ValueError(f"{name}: active {tag} requires develop to be checked out")
    dirty = git(
        repo,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    if dirty:
        raise ValueError(f"{name}: active {tag} requires a clean checkout:\n{dirty}")
    return Selection(name, repo, develop, version, True, tag)


def _stable(name: str, repo: Path) -> Selection:
    """Return the newest first-parent stable release reachable from main."""
    main = "origin/main" if _has_ref(repo, "origin/main") else "main"
    if not _has_ref(repo, main):
        raise ValueError(
            f"{name}: neither origin/main nor main is available for stable fallback"
        )
    tags = _tags(repo)
    by_commit: dict[str, list[str]] = {}
    for tag, commit in tags.items():
        if _STABLE.fullmatch(tag):
            by_commit.setdefault(commit, []).append(tag)
    for commit in git(repo, "rev-list", "--first-parent", main).splitlines():
        choices = by_commit.get(commit, [])
        if not choices:
            continue
        tag = max(
            choices, key=lambda item: tuple(map(int, _STABLE.fullmatch(item).groups()))
        )
        version = _project_version(repo, commit)
        if tag != f"v{version}":
            raise ValueError(
                f"{name}: stable tag {tag} does not match {commit} pyproject.toml version {version}"
            )
        return Selection(name, repo, commit, version, False, tag)
    raise ValueError(
        f"{name}: no exact stable vX.Y.Z tag exists on first-parent {main}"
    )


def select_modules(modules_dir: Path, names: list[str]) -> list[Selection]:
    """Select active rc0 candidates or first-parent stable fallbacks.

    :param modules_dir: Directory containing the module repositories.
    :param names: Ordered module directory names.
    :return: Immutable selected module revisions.
    :raises ValueError: If a repository, tag, branch, or version is unsuitable.
    """
    selections = []
    for name in names:
        repo = (modules_dir / name).resolve()
        if not repo.is_dir() or not (repo / ".git").exists():
            raise ValueError(f"{name}: repository is missing at {repo}")
        selections.append(_candidate(name, repo) or _stable(name, repo))
    if not selections:
        raise ValueError("no release modules were requested")
    if not any(selection.candidate for selection in selections):
        raise ValueError(
            "no active rc0 candidates were selected; a release batch has nothing to check"
        )
    return selections


def _git_entries(repo: Path) -> tuple[list[str], dict[str, str]] | None:
    """Return ordinary paths and gitlink commits, or ``None`` outside Git."""
    staged = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--stage", "-z"],
        capture_output=True,
        check=False,
    )
    if staged.returncode:
        return None
    gitlinks: dict[str, str] = {}
    for entry in staged.stdout.decode().split("\0"):
        if entry and entry.startswith("160000 "):
            _, path = entry.split("\t", 1)
            child = repo / path
            if not child.exists() or not (child / ".git").exists():
                raise ValueError(f"{repo}: tracked gitlink {path} is not checked out")
            gitlinks[path] = git(child, "rev-parse", "HEAD")
    listed = (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .split("\0")
    )
    return sorted({path for path in listed if path and path not in gitlinks}), gitlinks


def _include(path: str, code_only: bool) -> bool:
    """Return whether a relative path belongs in this fingerprint scope."""
    if not code_only:
        return True
    parts = Path(path).parts
    return not (
        parts[0] == "docs" or len(parts) == 1 and Path(path).suffix in {".md", ".rst"}
    )


def fingerprint(repo: Path, code_only: bool = False) -> str:
    """Hash tracked/nonignored files, modes, symlinks, and checked-out gitlinks.

    :param repo: Working tree or exported source directory.
    :param code_only: Exclude ``docs/**`` and root Markdown/reStructuredText prose.
    :return: A stable SHA-256 manifest digest.
    """
    entries = _git_entries(repo)
    if entries is None:
        paths = sorted(
            str(path.relative_to(repo))
            for path in repo.rglob("*")
            if (path.is_file() or path.is_symlink())
            and ".git" not in path.relative_to(repo).parts
        )
        gitlinks: dict[str, str] = {}
    else:
        paths, gitlinks = entries
    manifest: dict[str, object] = {}
    for name, commit in gitlinks.items():
        if _include(name, code_only):
            manifest[name] = {"gitlink": commit}
    for name in paths:
        if not _include(name, code_only):
            continue
        path = repo / name
        if not (path.is_file() or path.is_symlink()):
            continue
        if path.is_symlink():
            manifest[name] = {"symlink": os.readlink(path)}
        else:
            manifest[name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": bool(path.stat().st_mode & 0o111),
            }
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source_paths(source: Path) -> list[str]:
    """List regular files and symlinks in an exported source snapshot."""
    return sorted(
        str(path.relative_to(source))
        for path in source.rglob("*")
        if path.is_file() or path.is_symlink()
    )


def _manifest(source: Path, paths: list[str]) -> dict[str, object]:
    """Describe snapshot files precisely enough to detect gate mutations."""
    manifest: dict[str, object] = {}
    for name in paths:
        path = source / name
        if path.is_symlink():
            manifest[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            manifest[name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": bool(path.stat().st_mode & 0o111),
            }
    return manifest


def _assert_source_unchanged(
    repo: Path, source: Path, original: dict[str, object]
) -> None:
    """Reject gate changes except source additions ignored by the original repository."""
    if _manifest(source, list(original)) != original:
        raise ValueError(f"{repo}: a gate changed exported source files")
    added = sorted(set(_source_paths(source)).difference(original))
    if not added:
        return
    ignored = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "--no-index", "-z", "--stdin"],
        input="\0".join(added) + "\0",
        text=True,
        capture_output=True,
        check=False,
    )
    if ignored.returncode not in (0, 1):
        raise ValueError(
            f"{repo}: could not classify generated source files: {ignored.stderr}"
        )
    unexpected = sorted(set(added).difference(ignored.stdout.split("\0")))
    if unexpected:
        raise ValueError(f"{repo}: a gate added source files: {', '.join(unexpected)}")


def environment(venv: Path) -> dict[str, str]:
    """Return a scrubbed command environment rooted at *venv*."""
    excluded = {
        "VIRTUAL_ENV",
        "MAKEFLAGS",
        "MFLAGS",
        "MAKELEVEL",
        "MAKEFILES",
        "GNUMAKEFLAGS",
        "MYPYPATH",
        "NODE_OPTIONS",
        "PYTHON",
        "NODE",
        "NPM",
        "DIST_DIR",
        "DOCS_BASE_URL",
        "MEMGUARD",
        "TEST_TIMEOUT_SECONDS",
        "EXTENDED_TEST_TIMEOUT_SECONDS",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in excluded
        and not key.startswith(("PYTHON", "PYTEST", "PIP_", "UV_", "HTTK_", "CONDA_"))
    }
    paths = []
    for entry in os.environ.get("PATH", os.defpath).split(os.pathsep):
        path = Path(entry)
        if path.is_absolute() and not (path.resolve().parent / "pyvenv.cfg").is_file():
            paths.append(entry)
    env.update(
        PATH=os.pathsep.join([str(venv / "bin"), *paths]),
        PYTHONNOUSERSITE="1",
        PIP_CONFIG_FILE=os.devnull,
        UV_CONFIG_FILE=os.devnull,
        VIRTUAL_ENV=str(venv),
    )
    return env


def run(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
    """Run *command*, retaining output in *log* and raising on failure.

    :raises subprocess.CalledProcessError: If the command fails.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"Running {shlex.join(command)}\n  log: {log}", flush=True)
    with log.open("w") as output:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode:
        print(
            "\n".join(log.read_text(errors="replace").splitlines()[-30:]),
            file=sys.stderr,
        )
        raise subprocess.CalledProcessError(result.returncode, command)


def snapshot(selection: Selection, destination: Path) -> Path:
    """Export *selection*'s exact commit into a new *destination* directory."""
    if git(selection.repo, "rev-parse", selection.commit) != selection.commit:
        raise ValueError(
            f"{selection.name}: selected commit {selection.commit} no longer resolves"
        )
    tree = git(selection.repo, "ls-tree", "-rz", selection.commit).split("\0")
    if any(entry.startswith("160000 ") for entry in tree):
        raise ValueError(f"{selection.name}: snapshots with gitlinks are unsupported")
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination.with_suffix(".tar")
    try:
        with archive.open("wb") as output:
            subprocess.run(
                ["git", "-C", str(selection.repo), "archive", selection.commit],
                stdout=output,
                check=True,
            )
        with tarfile.open(archive) as exported:
            exported.extractall(destination, filter="data")
    finally:
        archive.unlink(missing_ok=True)
    # Git archive honours export-ignore/export-subst. Neither may silently
    # alter the exact source revision that the batch report claims to test.
    algorithm = git(selection.repo, "rev-parse", "--show-object-format")
    for entry in filter(None, tree):
        metadata, name = entry.split("\t", 1)
        mode, _kind, expected = metadata.split()
        path = destination / name
        if not path.is_file() and not path.is_symlink():
            raise ValueError(f"{selection.name}: archive omitted tracked file {name}")
        data = (
            os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        )
        digest = hashlib.new(
            algorithm, f"blob {len(data)}\0".encode() + data
        ).hexdigest()
        actual_mode = (
            "120000"
            if path.is_symlink()
            else "100755"
            if path.stat().st_mode & 0o111
            else "100644"
        )
        if digest != expected or actual_mode != mode:
            raise ValueError(f"{selection.name}: archive changed tracked file {name}")
    return destination


def save_state(path: Path, state: dict[str, object]) -> None:
    """Atomically write JSON release state to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def load_state(path: Path) -> dict[str, object]:
    """Load and minimally validate JSON release state from *path*."""
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load batch state {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError(f"{path}: expected batch state schema 1")
    return state


def _record(selection: Selection, code_fingerprint: str) -> dict[str, object]:
    """Serialize a selection in the state schema."""
    result = asdict(selection)
    result["repo"] = str(selection.repo)
    result["code_fingerprint"] = code_fingerprint
    return result


def _extras(source: Path) -> str:
    """Return the requested development/default extras declared by a source."""
    extras = tomllib.loads((source / "pyproject.toml").read_text())["project"].get(
        "optional-dependencies", {}
    )
    return ",".join(item for item in ("dev", "default") if item in extras)


def _constraint_lines(selections: list[Selection]) -> str:
    """Build exact candidate constraints for one complete resolver invocation."""
    return "".join(
        f"{selection.name.replace('_', '-')}=={selection.version}\n"
        for selection in selections
    )


def _imports(source: Path) -> list[str]:
    """Read the public import roots declared for versioned documentation."""
    config_path = source / "docs/versioning.toml"
    if not config_path.is_file():
        return []
    try:
        roots = tomllib.loads(config_path.read_text())["site"]["import-roots"]
    except (KeyError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(
            f"{source}: invalid docs/versioning.toml import-roots"
        ) from exc
    if not isinstance(roots, list) or not all(
        isinstance(root, str) and root for root in roots
    ):
        raise ValueError(f"{source}: docs/versioning.toml has invalid import-roots")
    return [root.replace("/", ".") for root in roots]


def _wheel_gate(
    selections: list[Selection], work: Path, sources: dict[str, Path], constraints: Path
) -> Path:
    """Build and check distributions once on Python 3.12, then smoke-import wheels."""
    wheels = work / "wheels"
    wheels.mkdir()
    batch_wheels = []
    venv = work / "venvs/3.12"
    env = environment(venv)
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin/python"),
            "--constraint",
            str(constraints),
            "build",
            "twine",
        ],
        work,
        env,
        work / "logs/3.12/build-tools.log",
    )
    for selection in selections:
        source = sources[selection.name]
        run(
            [str(venv / "bin/python"), "-m", "build", "--outdir", str(wheels)],
            source,
            env,
            work / f"logs/3.12/{selection.name}-build.log",
        )
        artifacts = sorted(
            str(path)
            for path in wheels.glob(
                f"{selection.name.replace('-', '_')}-{selection.version}*"
            )
        )
        run(
            [str(venv / "bin/python"), "-m", "twine", "check", "--strict", *artifacts],
            work,
            env,
            work / f"logs/3.12/{selection.name}-twine.log",
        )
        batch_wheels.extend(
            sorted(
                wheels.glob(
                    f"{selection.name.replace('-', '_')}-{selection.version}*.whl"
                )
            )
        )
    if len(batch_wheels) != len(selections):
        raise ValueError(
            "wheel build did not produce exactly one wheel per selected module"
        )
    smoke = work / "venvs/wheels"
    run(
        ["uv", "venv", "--seed", "--python", "3.12", str(smoke)],
        work,
        environment(smoke),
        work / "logs/wheels-venv.log",
    )
    smoke_env = environment(smoke)
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(smoke / "bin/python"),
            "--constraint",
            str(constraints),
            *map(str, batch_wheels),
        ],
        work,
        smoke_env,
        work / "logs/wheels-install.log",
    )
    run(
        ["uv", "pip", "check", "--python", str(smoke / "bin/python")],
        work,
        smoke_env,
        work / "logs/wheels-check.log",
    )
    imports = sorted({root for source in sources.values() for root in _imports(source)})
    if imports:
        run(
            [
                str(smoke / "bin/python"),
                "-c",
                "; ".join(f"import {root}" for root in imports),
            ],
            work,
            smoke_env,
            work / "logs/wheels-imports.log",
        )
    return wheels


def check_batch(selections: list[Selection], state_path: Path) -> dict[str, object]:
    """Snapshot and run all code gates for an exact batch, retaining evidence.

    :param selections: Selected, immutable revisions.
    :param state_path: Ignored local JSON state to create or replace.
    :return: The successful state dictionary.
    """
    old: dict[str, object] = {}
    if state_path.exists():
        old = load_state(state_path)
        if old.get("status") == "code-passed":
            old["status"] = "invalidated"
            old.pop("docs", None)
            save_state(state_path, old)
    work = Path(tempfile.mkdtemp(prefix="httk-release-batch-"))
    state: dict[str, object] = {
        "schema": 1,
        "status": "failed",
        "work": str(work),
        "selections": [],
    }
    save_state(state_path, state)
    try:
        sources = {
            selection.name: snapshot(selection, work / "sources" / selection.name)
            for selection in selections
        }
        originals = {
            name: _manifest(source, _source_paths(source))
            for name, source in sources.items()
        }
        records = [
            _record(selection, fingerprint(sources[selection.name], code_only=True))
            for selection in selections
        ]
        state["selections"] = records
        constraints = work / "constraints.txt"
        constraints.write_text(_constraint_lines(selections))
        for selection in selections:
            source = sources[selection.name]
            if (source / "package-lock.json").is_file():
                run(
                    ["npm", "ci"],
                    source,
                    environment(work / "venvs/3.12"),
                    work / f"logs/npm-{selection.name}.log",
                )
        for version in PYTHONS:
            venv = work / "venvs" / version
            env = environment(venv)
            run(
                ["uv", "venv", "--seed", "--python", version, str(venv)],
                work,
                env,
                work / f"logs/{version}-venv.log",
            )
            requirements = []
            for selection in selections:
                extra = _extras(sources[selection.name])
                requirement = str(sources[selection.name]) + (
                    f"[{extra}]" if extra else ""
                )
                requirements.extend(["-e", requirement])
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(venv / "bin/python"),
                    "--constraint",
                    str(constraints),
                    *requirements,
                ],
                work,
                env,
                work / f"logs/{version}-install.log",
            )
            run(
                ["uv", "pip", "check", "--python", str(venv / "bin/python")],
                work,
                env,
                work / f"logs/{version}-check.log",
            )
            run(
                ["uv", "pip", "freeze", "--python", str(venv / "bin/python")],
                work,
                env,
                work / f"logs/{version}-freeze.log",
            )
            for selection in selections:
                run(
                    ["make", "ci", f"PYTHON={venv / 'bin/python'}"],
                    sources[selection.name],
                    env,
                    work / f"logs/{version}-{selection.name}-ci.log",
                )
        state["wheels"] = str(_wheel_gate(selections, work, sources, constraints))
        for selection in selections:
            _assert_source_unchanged(
                selection.repo, sources[selection.name], originals[selection.name]
            )
        state["status"] = "code-passed"
        save_state(state_path, state)
        return state
    except BaseException:
        save_state(state_path, state)
        raise


def _selection(record: object) -> tuple[Selection, str]:
    """Parse one persisted state selection and fingerprint."""
    if not isinstance(record, dict):
        raise TypeError("batch state has an invalid selection")
    needed = {
        "name",
        "repo",
        "commit",
        "version",
        "candidate",
        "tag",
        "code_fingerprint",
    }
    strings = {"name", "repo", "commit", "version", "tag", "code_fingerprint"}
    if (
        set(record) != needed
        or not all(isinstance(record[key], str) for key in strings)
        or not isinstance(record["candidate"], bool)
    ):
        raise ValueError("batch state selection schema is invalid")
    return Selection(
        record["name"],
        Path(record["repo"]),
        record["commit"],
        record["version"],
        record["candidate"],
        record["tag"],
    ), record["code_fingerprint"]


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    """Return whether *older* is an ancestor of *newer*."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
            check=False,
        ).returncode
        == 0
    )


def verify_code(state: dict[str, object]) -> list[Selection]:
    """Revalidate code evidence, allowing only documentation/prose candidate changes.

    :param state: Previously loaded schema-1 batch state.
    :return: The revalidated selected revisions.
    :raises ValueError: If tags, ancestry, or code inputs drifted.
    """
    if state.get("schema") != 1 or state.get("status") != "code-passed":
        raise ValueError("batch code evidence is not successful schema-1 state")
    records = state.get("selections")
    if not isinstance(records, list) or not records:
        raise ValueError("batch code evidence has no selections")
    selections = []
    for record in records:
        selection, expected = _selection(record)
        if not selection.repo.is_dir():
            raise ValueError(
                f"{selection.name}: repository disappeared: {selection.repo}"
            )
        if _tags(selection.repo).get(selection.tag) != selection.commit:
            raise ValueError(
                f"{selection.name}: tag {selection.tag} moved or disappeared"
            )
        expected_tag = (
            f"v{selection.version}-rc0"
            if selection.candidate
            else f"v{selection.version}"
        )
        if selection.tag != expected_tag:
            raise ValueError(f"{selection.name}: persisted tag/version mismatch")
        if selection.candidate:
            if not _has_ref(selection.repo, "develop") or not _is_ancestor(
                selection.repo, selection.commit, "develop"
            ):
                raise ValueError(
                    f"{selection.name}: develop no longer descends from {selection.tag}"
                )
            actual = fingerprint(selection.repo, code_only=True)
        else:
            temporary = Path(tempfile.mkdtemp(prefix="httk-release-batch-verify-"))
            try:
                actual = fingerprint(
                    snapshot(selection, temporary / "source"), code_only=True
                )
            finally:
                shutil.rmtree(temporary)
        if actual != expected:
            raise ValueError(
                f"{selection.name}: code inputs changed since the batch check"
            )
        selections.append(selection)
    return selections
