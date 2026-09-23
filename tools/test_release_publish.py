"""Local-Git regression tests for final batch publication."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import release_publish
from tools.release_batch import Selection, fingerprint, git


def _run(*args: str, cwd: Path | None = None) -> str:
    """Run a checked command for a disposable Git fixture."""

    return subprocess.run(
        args, cwd=cwd, text=True, check=True, capture_output=True
    ).stdout.strip()


class PublicationFixture(unittest.TestCase):
    """A small batch with bare origins and an aggregate gitlink snapshot."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.modules: list[Selection] = []
        self.module_repos: dict[str, Path] = {}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _repository(
        self, name: str, dependencies: list[str] | None = None
    ) -> Selection:
        """Create a main/develop candidate repository and its bare origin."""

        remote = self.root / f"{name}.git"
        repo = self.root / name
        _run("git", "init", "--bare", str(remote))
        _run("git", "init", "-b", "main", str(repo))
        _run("git", "config", "user.name", "Test User", cwd=repo)
        _run("git", "config", "user.email", "test@example.invalid", cwd=repo)
        dependencies = dependencies or []
        project = [
            "[project]",
            f'name = "{name}"',
            'version = "1.0.0"',
            "dependencies = [",
            *(f'  "{dependency}",' for dependency in dependencies),
            "]",
            "[project.optional-dependencies]",
            "docs = []",
        ]
        (repo / "pyproject.toml").write_text("\n".join(project) + "\n")
        (repo / "code.py").write_text("main = True\n")
        _run("git", "add", ".", cwd=repo)
        _run("git", "commit", "-m", "main", cwd=repo)
        _run("git", "remote", "add", "origin", str(remote), cwd=repo)
        _run("git", "push", "-u", "origin", "main", cwd=repo)
        _run("git", "switch", "-c", "develop", cwd=repo)
        (repo / "code.py").write_text("candidate = True\n")
        _run("git", "commit", "-am", "candidate", cwd=repo)
        commit = _run("git", "rev-parse", "HEAD", cwd=repo)
        _run("git", "tag", "v1.0.0-rc0", cwd=repo)
        _run("git", "push", "-u", "origin", "develop", cwd=repo)
        selection = Selection(name, repo, commit, "1.0.0", True, "v1.0.0-rc0")
        self.modules.append(selection)
        self.module_repos[name] = repo
        return selection

    def _site(self) -> Path:
        """Create a clean, pushed aggregate site pinned to all candidates."""

        remote = self.root / "site.git"
        site = self.root / "site"
        _run("git", "init", "--bare", str(remote))
        _run("git", "init", "-b", "main", str(site))
        _run("git", "config", "user.name", "Test User", cwd=site)
        _run("git", "config", "user.email", "test@example.invalid", cwd=site)
        (site / "README.md").write_text("site\n")
        _run("git", "add", "README.md", cwd=site)
        _run("git", "commit", "-m", "site", cwd=site)
        for selection in self.modules:
            path = f"submodules/{selection.name}"
            _run(
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(selection.repo),
                path,
                cwd=site,
            )
            nested = site / path
            commit = (
                git(selection.repo, "rev-parse", "develop")
                if selection.candidate
                else selection.commit
            )
            _run("git", "checkout", "--detach", commit, cwd=nested)
            _run("git", "add", path, cwd=site)
        _run("git", "commit", "-m", "pins", cwd=site)
        _run("git", "remote", "add", "origin", str(remote), cwd=site)
        _run("git", "push", "-u", "origin", "main", cwd=site)
        return site

    def _state(self, site: Path) -> Path:
        """Write successful code/docs evidence matching the fixture."""

        records = []
        for selection in self.modules:
            records.append(
                {
                    "name": selection.name,
                    "repo": str(selection.repo),
                    "commit": selection.commit,
                    "version": selection.version,
                    "candidate": selection.candidate,
                    "tag": selection.tag,
                    "code_fingerprint": fingerprint(selection.repo, code_only=True),
                }
            )
        state = {
            "schema": 1,
            "status": "code-passed",
            "selections": records,
            "docs": {
                "status": "passed",
                "fingerprints": {
                    selection.name: fingerprint(selection.repo)
                    for selection in self.modules
                },
                "site": {
                    "repo": str(site),
                    "fingerprint": fingerprint(site),
                    "heads": {
                        selection.name: git(selection.repo, "rev-parse", "develop")
                        if selection.candidate
                        else selection.commit
                        for selection in self.modules
                    },
                },
            },
        }
        path = self.root / "state.json"
        path.write_text(json.dumps(state))
        return path

    def _unsigned_signer(
        self, commands: list[tuple[Path, tuple[str, ...]]] | None = None
    ):
        """Replace only signing with an annotated tag for disposable test keys."""

        original = release_publish.git

        def fake(repo: Path, *args: str) -> str:
            if commands is not None:
                commands.append((repo, args))
            if "tag" in args and "-s" in args:
                tag_at = args.index("tag")
                tag = args[tag_at + 4]
                commit = args[tag_at + 5]
                return original(repo, "tag", "-a", "-m", tag, tag, commit)
            if args[:1] == ("verify-tag",):
                return ""
            return original(repo, *args)

        return fake

    def test_late_dirty_candidate_changes_no_refs(self) -> None:
        """A later preflight failure leaves an earlier candidate untouched."""

        first = self._repository("first")
        second = self._repository("second")
        site = self._site()
        state = self._state(site)
        (second.repo / "docs").mkdir()
        (second.repo / "docs" / "note.txt").write_text("untracked but code-only safe\n")
        evidence = json.loads(state.read_text())
        evidence["docs"]["fingerprints"]["second"] = fingerprint(second.repo)
        state.write_text(json.dumps(evidence))
        before_main = git(first.repo, "rev-parse", "refs/heads/main")

        with self.assertRaises(release_publish.PublicationError):
            release_publish.publish(state, "Test User", "test@example.invalid")

        self.assertEqual(before_main, git(first.repo, "rev-parse", "refs/heads/main"))
        self.assertEqual(
            before_main,
            _run(
                "git", "ls-remote", "origin", "refs/heads/main", cwd=first.repo
            ).split()[0],
        )
        self.assertIsNone(release_publish._local_tag_commit(first.repo, "v1.0.0"))

    def test_stale_local_main_can_fast_forward(self) -> None:
        """Pulling develop need not advance an older local main checkout ref."""
        selection = self._repository("only")
        git(selection.repo, "push", "origin", "develop:main")
        (selection.repo / "README.md").write_text("Verified docs commit\n")
        git(selection.repo, "add", "README.md")
        git(selection.repo, "commit", "-m", "docs")
        git(selection.repo, "push", "origin", "develop")
        final = git(selection.repo, "rev-parse", "HEAD")
        state = self._state(self._site())
        with patch.object(release_publish, "git", side_effect=self._unsigned_signer()):
            release_publish.publish(state, "Test User", "test@example.invalid")
        self.assertEqual(git(selection.repo, "rev-parse", "main"), final)

    def test_groups_include_new_versions_pinned_through_stable_dependencies(
        self,
    ) -> None:
        """A generated docs lock needs transitive candidate versions published."""
        core = self._repository("httk-core")
        bridge = self._repository("httk-bridge", ["httk-core>=0.9"])
        stable_bridge = Selection(
            bridge.name, bridge.repo, bridge.commit, bridge.version, False, "v1.0.0"
        )
        consumer = self._repository("httk-consumer", ["httk-bridge>=1.0"])
        (consumer.repo / "docs").mkdir()
        (consumer.repo / "docs/requirements.lock").write_text(
            "httk-core==1.0.0\nhttk-bridge==1.0.0\n"
        )
        self.assertEqual(
            release_publish.release_groups([consumer, stable_bridge, core]),
            [["httk-core"], ["httk-consumer"]],
        )

    def test_stale_documentation_evidence_is_rejected(self) -> None:
        """A changed committed aggregate snapshot cannot authorize release refs."""

        candidate = self._repository("only")
        site = self._site()
        state = self._state(site)
        (site / "README.md").write_text("changed\n")
        _run("git", "commit", "-am", "changed", cwd=site)
        _run("git", "push", cwd=site)

        with self.assertRaisesRegex(
            release_publish.PublicationError, "fingerprint is stale"
        ):
            release_publish.publish(state, "Test User", "test@example.invalid")

        self.assertIsNone(release_publish._remote_tag_commit(candidate.repo, "v1.0.0"))

    def test_docs_only_commit_after_rc0_is_the_final_tag(self) -> None:
        """The final tag follows the validated docs commit, not the original rc0."""

        candidate = self._repository("only")
        (candidate.repo / "docs").mkdir()
        (candidate.repo / "docs" / "release.md").write_text("release notes\n")
        _run("git", "add", "docs", cwd=candidate.repo)
        _run("git", "commit", "-m", "docs", cwd=candidate.repo)
        final = git(candidate.repo, "rev-parse", "HEAD")
        _run("git", "push", cwd=candidate.repo)
        site = self._site()
        state = self._state(site)

        with patch.object(release_publish, "git", self._unsigned_signer()):
            release_publish.publish(state, "Test User", "test@example.invalid")

        self.assertNotEqual(candidate.commit, final)
        self.assertEqual(
            final, release_publish._remote_tag_commit(candidate.repo, "v1.0.0")
        )

    def test_local_lightweight_final_tag_is_rejected_before_main_changes(self) -> None:
        """An exact but unsigned local final tag cannot be silently reused."""

        candidate = self._repository("only")
        site = self._site()
        state = self._state(site)
        _run("git", "tag", "v1.0.0", cwd=candidate.repo)
        before_main = git(candidate.repo, "rev-parse", "refs/heads/main")

        with self.assertRaisesRegex(
            release_publish.PublicationError, "annotated signed"
        ):
            release_publish.publish(state, "Test User", "test@example.invalid")

        self.assertEqual(
            before_main, git(candidate.repo, "rev-parse", "refs/heads/main")
        )
        self.assertEqual(
            before_main,
            _run(
                "git", "ls-remote", "origin", "refs/heads/main", cwd=candidate.repo
            ).split()[0],
        )

    def test_remote_lightweight_final_tag_is_rejected_before_main_changes(self) -> None:
        """A remote-only lightweight final tag cannot be silently reused."""

        candidate = self._repository("only")
        site = self._site()
        state = self._state(site)
        _run("git", "tag", "v1.0.0", cwd=candidate.repo)
        _run(
            "git",
            "push",
            "origin",
            "refs/tags/v1.0.0:refs/tags/v1.0.0",
            cwd=candidate.repo,
        )
        _run("git", "tag", "-d", "v1.0.0", cwd=candidate.repo)
        before_main = git(candidate.repo, "rev-parse", "refs/heads/main")

        with self.assertRaisesRegex(
            release_publish.PublicationError, "annotated signed"
        ):
            release_publish.publish(state, "Test User", "test@example.invalid")

        self.assertEqual(
            before_main, git(candidate.repo, "rev-parse", "refs/heads/main")
        )
        self.assertEqual(
            before_main,
            _run(
                "git", "ls-remote", "origin", "refs/heads/main", cwd=candidate.repo
            ).split()[0],
        )
        self.assertIsNone(release_publish._local_tag_commit(candidate.repo, "v1.0.0"))

    def test_retry_completes_half_published_batch_without_force(self) -> None:
        """A retry preserves the first atomic result and finishes the remainder."""

        first = self._repository("first")
        second = self._repository("second")
        site = self._site()
        state = self._state(site)
        commands: list[tuple[Path, tuple[str, ...]]] = []
        signer = self._unsigned_signer(commands)
        failed = False

        def fail_second_push(repo: Path, *args: str) -> str:
            nonlocal failed
            if repo == second.repo and args[:1] == ("push",) and not failed:
                failed = True
                raise subprocess.CalledProcessError(1, ["git", *args])
            return signer(repo, *args)

        with (
            patch.object(release_publish, "git", fail_second_push),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            release_publish.publish(state, "Test User", "test@example.invalid")
        self.assertEqual(
            first.commit, release_publish._remote_tag_commit(first.repo, "v1.0.0")
        )
        self.assertIsNone(release_publish._remote_tag_commit(second.repo, "v1.0.0"))

        with patch.object(release_publish, "git", signer):
            release_publish.publish(state, "Test User", "test@example.invalid")
        self.assertEqual(
            second.commit, release_publish._remote_tag_commit(second.repo, "v1.0.0")
        )
        pushes = [args for _, args in commands if args[:1] == ("push",)]
        self.assertTrue(pushes)
        self.assertTrue(all("--force" not in args for args in pushes))

    def test_release_groups_use_optional_dependencies_and_reject_cycles(self) -> None:
        """Candidate extras order groups, while cycles stop publication planning."""

        core = self._repository("core")
        addon = self._repository("addon", ["core[docs]>=1"])
        self.assertEqual(
            [["core"], ["addon"]], release_publish.release_groups([core, addon])
        )

        left = self._repository("left", ["right>=1"])
        right = self._repository("right", ["left>=1"])
        with self.assertRaisesRegex(release_publish.PublicationError, "cycle"):
            release_publish.release_groups([left, right])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
