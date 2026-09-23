"""Focused Git-fixture tests for :mod:`tools.release_batch`."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "release_batch", Path(__file__).with_name("release_batch.py")
)
release_batch = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(release_batch)


def _git(repo: Path, *args: str) -> str:
    """Run a checked fixture Git command."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True
    ).stdout.strip()


class ReleaseBatchTests(unittest.TestCase):
    """Exercise selection and evidence using disposable local repositories."""

    def setUp(self) -> None:
        """Create an isolated fixtures directory."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.modules = self.root / "modules"
        self.modules.mkdir()

    def tearDown(self) -> None:
        """Remove fixture repositories."""
        self.temporary.cleanup()

    def repo(self, name: str = "mod", version: str = "1.0.0") -> Path:
        """Create a module repository with an initial main commit."""
        repo = self.modules / name
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "Test")
        self.write_project(repo, name, version)
        (repo / "src" / "httk" / name.replace("-", "_")).mkdir(parents=True)
        (repo / "src" / "httk" / name.replace("-", "_") / "__init__.py").write_text("")
        (repo / "Makefile").write_text("ci:\n\t@true\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "initial")
        return repo

    def write_project(self, repo: Path, name: str, version: str) -> None:
        """Write minimal package metadata, including the requested extras."""
        (repo / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
            f"[project]\nname = '{name}'\nversion = '{version}'\n"
            "[project.optional-dependencies]\ndev = []\ndefault = []\n"
        )

    def commit(self, repo: Path, message: str = "change") -> str:
        """Commit all fixture changes and return the commit ID."""
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", message)
        return _git(repo, "rev-parse", "HEAD")

    def test_selects_clean_rc0_at_develop(self) -> None:
        """A single matching rc0 on clean develop wins over stable fallback."""
        repo = self.repo(version="1.0.0")
        _git(repo, "tag", "v1.0.0")
        _git(repo, "switch", "-c", "develop")
        self.write_project(repo, "mod", "1.1.0")
        commit = self.commit(repo, "candidate")
        _git(repo, "tag", "v1.1.0-rc0")

        selection = release_batch.select_modules(self.modules, ["mod"])[0]

        self.assertEqual(selection.commit, commit)
        self.assertTrue(selection.candidate)
        self.assertEqual(selection.tag, "v1.1.0-rc0")

    def test_falls_back_to_newest_first_parent_origin_main(self) -> None:
        """Stable fallback prefers origin/main and ignores a later local main tag."""
        repo = self.repo(version="1.0.0")
        first = _git(repo, "rev-parse", "HEAD")
        _git(repo, "tag", "v1.0.0")
        _git(repo, "update-ref", "refs/remotes/origin/main", first)
        self.write_project(repo, "mod", "2.0.0")
        second = self.commit(repo, "local main")
        _git(repo, "tag", "v2.0.0")

        selection = release_batch._stable("mod", repo)

        self.assertEqual(selection.commit, first)
        self.assertEqual(selection.tag, "v1.0.0")
        self.assertFalse(selection.candidate)
        self.assertNotEqual(selection.commit, second)

    def test_rejects_empty_or_all_stable_batches(self) -> None:
        """A release batch needs at least one active rc0 candidate."""
        repo = self.repo()
        _git(repo, "tag", "v1.0.0")
        with self.assertRaisesRegex(ValueError, "no release modules"):
            release_batch.select_modules(self.modules, [])
        with self.assertRaisesRegex(ValueError, "no active rc0"):
            release_batch.select_modules(self.modules, ["mod"])

    def test_rejects_dirty_or_version_mismatched_candidate(self) -> None:
        """Candidate branch cleanliness and tag/metadata agreement are mandatory."""
        repo = self.repo()
        _git(repo, "switch", "-c", "develop")
        _git(repo, "tag", "v1.0.0-rc0")
        (repo / "untracked.py").write_text("x = 1\n")
        with self.assertRaisesRegex(ValueError, "clean checkout"):
            release_batch.select_modules(self.modules, ["mod"])
        (repo / "untracked.py").unlink()
        _git(repo, "tag", "-d", "v1.0.0-rc0")
        _git(repo, "tag", "v9.9.9-rc0")
        with self.assertRaisesRegex(ValueError, "does not match"):
            release_batch.select_modules(self.modules, ["mod"])

    def test_finalised_rc0_is_not_an_active_candidate(self) -> None:
        """A matching final tag makes the rc0 historical rather than selectable."""
        repo = self.repo()
        _git(repo, "tag", "v1.0.0")
        _git(repo, "switch", "-c", "develop")
        _git(repo, "tag", "v1.0.0-rc0")

        self.assertIsNone(release_batch._candidate("mod", repo))
        with self.assertRaisesRegex(ValueError, "no active rc0"):
            release_batch.select_modules(self.modules, ["mod"])

    def test_fingerprint_excludes_only_documentation_scope_and_records_gitlinks(
        self,
    ) -> None:
        """Docs prose is reusable; source/nested prose and gitlink heads are not."""
        repo = self.repo()
        (repo / "README.md").write_text("one\n")
        (repo / "docs").mkdir()
        (repo / "docs" / "guide.py").write_text("one\n")
        (repo / "nested").mkdir()
        (repo / "nested" / "README.md").write_text("one\n")
        self.commit(repo, "docs")
        original = release_batch.fingerprint(repo, code_only=True)
        (repo / "README.md").write_text("two\n")
        (repo / "docs" / "guide.py").write_text("two\n")
        self.assertEqual(original, release_batch.fingerprint(repo, code_only=True))
        (repo / "nested" / "README.md").write_text("two\n")
        self.assertNotEqual(original, release_batch.fingerprint(repo, code_only=True))

        child = repo / "child"
        child.mkdir()
        _git(child, "init")
        _git(child, "config", "user.email", "test@example.invalid")
        _git(child, "config", "user.name", "Test")
        (child / "entry").write_text("one\n")
        _git(child, "add", ".")
        _git(child, "commit", "-m", "one")
        _git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{_git(child, 'rev-parse', 'HEAD')},child",
        )
        _git(repo, "commit", "-m", "gitlink")
        linked = release_batch.fingerprint(repo)
        (child / "entry").write_text("two\n")
        _git(child, "add", ".")
        _git(child, "commit", "-m", "two")
        self.assertNotEqual(linked, release_batch.fingerprint(repo))

    def test_verify_rejects_moved_tag_but_allows_documentation_commit(self) -> None:
        """Candidate evidence permits docs-only develop descendants, never moved tags."""
        repo = self.repo()
        _git(repo, "switch", "-c", "develop")
        candidate = _git(repo, "rev-parse", "HEAD")
        _git(repo, "tag", "v1.0.0-rc0")
        source = self.root / "source"
        release_batch.snapshot(
            release_batch.Selection(
                "mod", repo, candidate, "1.0.0", True, "v1.0.0-rc0"
            ),
            source,
        )
        state = {
            "schema": 1,
            "status": "code-passed",
            "work": str(self.root),
            "selections": [
                {
                    "name": "mod",
                    "repo": str(repo),
                    "commit": candidate,
                    "version": "1.0.0",
                    "candidate": True,
                    "tag": "v1.0.0-rc0",
                    "code_fingerprint": release_batch.fingerprint(
                        source, code_only=True
                    ),
                }
            ],
        }
        (repo / "docs").mkdir()
        (repo / "docs" / "note.rst").write_text("note\n")
        self.commit(repo, "docs only")
        self.assertEqual(release_batch.verify_code(state)[0].commit, candidate)
        _git(repo, "tag", "-f", "v1.0.0-rc0")
        with self.assertRaisesRegex(ValueError, "moved"):
            release_batch.verify_code(state)

    def test_snapshot_gate_mutation_rejects_unignored_additions(self) -> None:
        """Snapshot gates may add ignored cache files, never source inputs."""
        repo = self.repo()
        source = self.root / "source"
        selection = release_batch.Selection(
            "mod", repo, _git(repo, "rev-parse", "HEAD"), "1.0.0", False, "v1.0.0"
        )
        release_batch.snapshot(selection, source)
        original = release_batch._manifest(source, release_batch._source_paths(source))
        (repo / ".gitignore").write_text("generated/\n")
        self.commit(repo, "ignore generated")
        (source / "generated").mkdir()
        (source / "generated" / "cache").write_text("cache\n")
        release_batch._assert_source_unchanged(repo, source, original)
        (source / "new.py").write_text("new\n")
        with self.assertRaisesRegex(ValueError, "added source files"):
            release_batch._assert_source_unchanged(repo, source, original)

    def test_archive_attributes_cannot_silently_change_checked_source(self) -> None:
        """Both archive omissions and content substitution reject the snapshot."""
        repo = self.repo()
        (repo / "runtime.py").write_text('VERSION = "$Format:%H$"\n')
        for attribute, message in (
            ("export-ignore", "omitted"),
            ("export-subst", "changed"),
        ):
            with self.subTest(attribute=attribute):
                (repo / ".gitattributes").write_text(f"runtime.py {attribute}\n")
                commit = self.commit(repo, attribute)
                selected = release_batch.Selection(
                    "mod", repo, commit, "1.0.0", False, "v1.0.0"
                )
                with self.assertRaisesRegex(
                    ValueError, f"archive {message} tracked file runtime.py"
                ):
                    release_batch.snapshot(selected, self.root / attribute)

    def test_failed_run_replaces_prior_success_and_gates_never_request_docs(
        self,
    ) -> None:
        """A new attempt invalidates success; the code command plan contains no docs target."""
        repo = self.repo()
        commit = _git(repo, "rev-parse", "HEAD")
        selection = release_batch.Selection(
            "mod", repo, commit, "1.0.0", False, "v1.0.0"
        )
        state_path = self.root / "state.json"
        release_batch.save_state(
            state_path,
            {"schema": 1, "status": "code-passed", "work": "old", "selections": []},
        )
        with (
            self.assertRaises(subprocess.CalledProcessError),
            patch.object(
                release_batch,
                "snapshot",
                side_effect=subprocess.CalledProcessError(1, ["git"]),
            ),
        ):
            release_batch.check_batch([selection], state_path)
        self.assertEqual(release_batch.load_state(state_path)["status"], "failed")

        commands: list[list[str]] = []
        work = self.root / "work"

        def capture(
            command: list[str], cwd: Path, env: dict[str, str], log: Path
        ) -> None:
            commands.append(command)

        with (
            patch.object(release_batch.tempfile, "mkdtemp", return_value=str(work)),
            patch.object(release_batch, "run", side_effect=capture),
            patch.object(release_batch, "_wheel_gate", return_value=work / "wheels"),
        ):
            release_batch.check_batch([selection], state_path)
        rendered = [" ".join(command) for command in commands]
        self.assertTrue(
            any(command.startswith("make ci PYTHON=") for command in rendered)
        )
        self.assertTrue(
            any("uv pip install" in command and "-e" in command for command in rendered)
        )
        self.assertFalse(any("docs" in command for command in rendered))
        self.assertEqual(release_batch.load_state(state_path)["status"], "code-passed")

    def test_gate_failure_stops_before_later_commands(self) -> None:
        """The first failed isolated command is fail-fast evidence."""
        repo = self.repo()
        selection = release_batch.Selection(
            "mod", repo, _git(repo, "rev-parse", "HEAD"), "1.0.0", True, "v1.0.0-rc0"
        )
        state = self.root / "state.json"
        calls = []

        def fail(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
            calls.append(command)
            raise subprocess.CalledProcessError(1, command)

        with (
            patch.object(release_batch, "run", side_effect=fail),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            release_batch.check_batch([selection], state)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["uv", "venv", "--seed"])

    def test_wheel_smoke_uses_built_wheel_paths_and_documented_roots(self) -> None:
        """Smoke installation names local wheels directly and imports docs roots."""
        source = self.root / "source"
        source.mkdir()
        self.write_project(source, "mod", "1.0.0")
        (source / "docs").mkdir()
        (source / "docs" / "versioning.toml").write_text(
            '[site]\nimport-roots = ["httk/serve"]\n'
        )
        work = self.root / "work"
        work.mkdir()
        constraints = work / "constraints.txt"
        constraints.write_text("mod==1.0.0\n")
        selection = release_batch.Selection(
            "mod", source, "unused", "1.0.0", True, "v1.0.0-rc0"
        )
        commands = []

        def capture(
            command: list[str], cwd: Path, env: dict[str, str], log: Path
        ) -> None:
            commands.append(command)
            if command[1:4] == ["-m", "build", "--outdir"]:
                wheels = Path(command[4])
                wheels.mkdir(exist_ok=True)
                (wheels / "mod-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
                (wheels / "mod-1.0.0.tar.gz").write_bytes(b"sdist")

        with patch.object(release_batch, "run", side_effect=capture):
            release_batch._wheel_gate([selection], work, {"mod": source}, constraints)
        install = next(
            command
            for command in commands
            if command[:3] == ["uv", "pip", "install"]
            and any(str(item).endswith(".whl") for item in command)
        )
        self.assertNotIn("--find-links", install)
        self.assertTrue(any(str(item).endswith(".whl") for item in install))
        imports = next(
            command
            for command in commands
            if command[1:3] == ["-c", "import httk.serve"]
        )
        self.assertEqual(imports[-1], "import httk.serve")


if __name__ == "__main__":
    unittest.main()
