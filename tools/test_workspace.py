"""Exercise workspace Makefile operations against disposable Git remotes."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WorkspaceTests(unittest.TestCase):
    """Check branch selection and real fast-forward pulls without network access."""

    def setUp(self) -> None:
        """Create an isolated workspace and disable personal Git configuration."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.remotes = self.root / "remotes"
        self.remotes.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME="Workspace test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Workspace test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
        )
        self.git(self.workspace, "init", "-b", "main")
        source = Path(__file__).resolve().parents[1]
        shutil.copy(source / "Makefile", self.workspace)
        shutil.copytree(source / "tools", self.workspace / "tools")
        self.git(self.workspace, "add", ".")
        self.git(self.workspace, "commit", "-m", "Workspace")
        self.git(self.root, "clone", "--bare", str(self.workspace), "workspace.git")
        self.git(
            self.workspace, "remote", "add", "origin", str(self.root / "workspace.git")
        )
        self.fixture("docs")

    def git(self, repo: Path, *args: str) -> str:
        """Run Git in the fixture environment and return its output."""
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            env=self.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def fixture(self, name: str, *, develop: bool = False, clone: bool = True) -> Path:
        """Create a remote and optionally a main-branch workspace clone."""
        source = self.root / name
        source.mkdir()
        self.git(source, "init", "-b", "main")
        (source / "tools").mkdir()
        (source / "tools/check_release.py").write_text("# Release tooling marker\n")
        self.git(source, "add", ".")
        self.git(source, "commit", "-m", "Initial")
        if develop:
            self.git(source, "branch", "develop")
        self.git(
            self.root, "clone", "--bare", str(source), str(self.remotes / f"{name}.git")
        )
        target = self.workspace / "modules" / name
        if clone:
            self.git(
                self.workspace, "clone", str(self.remotes / f"{name}.git"), str(target)
            )
        return target

    def make(self, target: str, *, check: bool = True) -> subprocess.CompletedProcess:
        """Run the real Makefile with only fixture repositories selected."""
        result = subprocess.run(
            [
                "make",
                target,
                "HTTK_DEFAULT_MODULES=mod",
                "HTTK_DOCS_REPOSITORY=docs",
                f"HTTK_GIT_BASE={self.remotes}",
                f"PYTHON={sys.executable}",
            ],
            cwd=self.workspace,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_main_only_retains_current_branch(self) -> None:
        """A release-tooling repository without develop keeps a feature branch."""
        repo = self.fixture("mod")
        self.git(repo, "switch", "-c", "feature")
        result = self.make("checkout")
        self.assertIn("no develop branch; keeping feature", result.stdout)
        self.assertEqual(self.git(repo, "branch", "--show-current"), "feature")

    def test_local_develop_needs_no_remote_lookup(self) -> None:
        """An existing local develop branch is selected even while offline."""
        repo = self.fixture("mod")
        self.git(repo, "branch", "develop")
        self.git(repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        self.make("checkout")
        self.assertEqual(self.git(repo, "branch", "--show-current"), "develop")

    def test_remote_develop_with_narrow_fetch_refspec(self) -> None:
        """Explicit fetching creates origin/develop even in single-branch clones."""
        repo = self.fixture("mod", develop=True, clone=False)
        self.git(
            self.workspace,
            "clone",
            "--single-branch",
            "--branch",
            "main",
            str(self.remotes / "mod.git"),
            str(repo),
        )
        self.make("checkout")
        self.assertEqual(self.git(repo, "branch", "--show-current"), "develop")
        self.assertEqual(
            self.git(repo, "config", "branch.develop.merge"), "refs/heads/develop"
        )

    def test_new_clone_without_develop_uses_default_branch(self) -> None:
        """A missing main-only module can be cloned by checkout."""
        repo = self.fixture("mod", clone=False)
        self.make("checkout")
        self.assertEqual(self.git(repo, "branch", "--show-current"), "main")

    def test_remote_failure_is_not_missing_branch(self) -> None:
        """Remote access errors fail checkout without changing the branch."""
        repo = self.fixture("mod")
        self.git(repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        result = self.make("checkout", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("no develop branch", result.stdout)
        self.assertEqual(self.git(repo, "branch", "--show-current"), "main")

    def test_pull_does_not_require_main_in_modules(self) -> None:
        """A module with only a differently named default branch still pulls."""
        repo = self.fixture("mod")
        remote = self.remotes / "mod.git"
        self.git(remote, "branch", "-m", "main", "trunk")
        self.git(repo, "branch", "-m", "main", "trunk")
        self.make("pull")
        self.assertEqual(self.git(repo, "branch", "--show-current"), "trunk")

    def test_pull_fast_forwards_main_only_and_develop_modules(self) -> None:
        """Pull uses the selected branch for mixed release-tooling repositories."""
        main_repo = self.fixture("mod")
        develop_repo = self.fixture("extra", develop=True)
        for name, branch in (("mod", "main"), ("extra", "develop")):
            source = self.root / name
            self.git(source, "switch", branch)
            (source / "new.txt").write_text(branch)
            self.git(source, "add", ".")
            self.git(source, "commit", "-m", "Remote update")
            self.git(source, "push", str(self.remotes / f"{name}.git"), branch)
        self.make("pull")
        self.assertEqual((main_repo / "new.txt").read_text(), "main")
        self.assertEqual((develop_repo / "new.txt").read_text(), "develop")
        self.assertEqual(self.git(main_repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(develop_repo, "branch", "--show-current"), "develop")


if __name__ == "__main__":
    unittest.main()
