"""Tests for :mod:`tools.workspace_remotes`."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import workspace_remotes


class WorkspaceRemotesTests(unittest.TestCase):
    """Exercise public remote conversion and submodule configuration."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="httk-remotes-test-")
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.root,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    def repository(self, name: str) -> Path:
        path = self.root / name
        self.git("init", "--quiet", str(path))
        self.git("config", "user.name", "Test", cwd=path)
        self.git("config", "user.email", "test@example.invalid", cwd=path)
        return path

    def test_public_origin_gets_https_fetch_and_ssh_push(self) -> None:
        """Convert a public SSH origin and remain idempotent."""

        repository = self.repository("repo")
        self.git(
            "remote", "add", "origin", "git@github.com:httk/example.git", cwd=repository
        )

        workspace_remotes.configure_repository(repository, probe=lambda url: True)
        self.assertEqual(
            "https://github.com/httk/example.git",
            self.git("config", "--get", "remote.origin.url", cwd=repository),
        )
        self.assertEqual(
            "git@github.com:httk/example.git",
            self.git("config", "--get-all", "remote.origin.pushurl", cwd=repository),
        )

        workspace_remotes.configure_repository(repository, probe=lambda url: True)
        self.assertEqual(
            "git@github.com:httk/example.git",
            self.git("config", "--get-all", "remote.origin.pushurl", cwd=repository),
        )

    def test_private_origin_and_custom_push_are_preserved(self) -> None:
        """Leave private fetches and custom push destinations untouched."""

        private = self.repository("private")
        self.git(
            "remote", "add", "origin", "git@github.com:httk/private.git", cwd=private
        )
        workspace_remotes.configure_repository(private, probe=lambda url: False)
        self.assertEqual(
            "git@github.com:httk/private.git",
            self.git("config", "--get", "remote.origin.url", cwd=private),
        )

        custom = self.repository("custom")
        self.git(
            "remote", "add", "origin", "https://github.com/httk/example.git", cwd=custom
        )
        self.git(
            "config",
            "--add",
            "remote.origin.pushurl",
            "ssh://git@example.invalid/custom",
            cwd=custom,
        )
        workspace_remotes.configure_repository(custom, probe=lambda url: True)
        self.assertEqual(
            "https://github.com/httk/example.git",
            self.git("config", "--get", "remote.origin.url", cwd=custom),
        )
        self.assertEqual(
            "ssh://git@example.invalid/custom",
            self.git("config", "--get-all", "remote.origin.pushurl", cwd=custom),
        )

    def test_nested_initialized_and_uninitialized_submodules(self) -> None:
        """Configure initialized and uninitialized registered submodules."""

        parent = self.repository("parent")
        child = self.repository("parent/child")
        self.git("remote", "add", "origin", "git@github.com:httk/child.git", cwd=child)
        self.git(
            "config",
            "--add",
            "remote.origin.pushurl",
            "ssh://git@example.invalid/custom",
            cwd=child,
        )
        gitfile = parent / "gitfile"
        self.git(
            "init",
            "--quiet",
            "--separate-git-dir",
            str(self.root / "gitfile.git"),
            str(gitfile),
        )
        self.git(
            "remote", "add", "origin", "git@github.com:httk/gitfile.git", cwd=gitfile
        )
        self.git(
            "remote", "add", "origin", "git@github.com:httk/parent.git", cwd=parent
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.child.path",
            "child",
            cwd=parent,
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.child.url",
            "git@github.com:httk/child.git",
            cwd=parent,
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.missing.path",
            "missing",
            cwd=parent,
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.missing.url",
            "https://github.com/httk/missing.git",
            cwd=parent,
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.gitfile.path",
            "gitfile",
            cwd=parent,
        )
        self.git(
            "config",
            "--file",
            ".gitmodules",
            "submodule.gitfile.url",
            "git@github.com:httk/gitfile.git",
            cwd=parent,
        )
        (parent / "missing").mkdir()

        workspace_remotes.configure_repository(parent, probe=lambda url: True)
        self.assertEqual(
            "https://github.com/httk/child.git",
            self.git("config", "--get", "remote.origin.url", cwd=child),
        )
        self.assertEqual(
            "ssh://git@example.invalid/custom",
            self.git("config", "--get", "remote.origin.pushurl", cwd=child),
        )
        self.assertEqual(
            "https://github.com/httk/gitfile.git",
            self.git("config", "--get", "remote.origin.url", cwd=gitfile),
        )
        self.assertEqual(
            "https://github.com/httk/missing.git",
            self.git("config", "--get", "submodule.missing.url", cwd=parent),
        )
        # Give sync real gitlink entries, including the separate-git-dir child.
        for repository in (child, gitfile):
            self.git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "Fixture",
                cwd=repository,
            )
        self.git("add", ".gitmodules", "child", "gitfile", cwd=parent)
        registered = (parent / ".gitmodules").read_bytes()
        self.git("submodule", "sync", "--recursive", cwd=parent)
        self.assertEqual(
            "git@github.com:httk/gitfile.git",
            self.git("config", "--get", "remote.origin.url", cwd=gitfile),
        )
        workspace_remotes.configure_repository(parent, probe=lambda url: True)
        self.assertEqual(
            "https://github.com/httk/gitfile.git",
            self.git("config", "--get", "remote.origin.url", cwd=gitfile),
        )
        self.assertEqual(
            "git@github.com:httk/gitfile.git",
            self.git("config", "--get", "remote.origin.pushurl", cwd=gitfile),
        )
        self.assertEqual(registered, (parent / ".gitmodules").read_bytes())

    def test_cli_configures_explicit_targets_without_persistent_opt_in(self) -> None:
        """Configure explicitly supplied targets without storing state."""

        target = self.repository("target")
        self.git(
            "remote", "add", "origin", "git@github.com:httk/example.git", cwd=target
        )
        with (
            mock.patch("tools.workspace_remotes._Configurator") as configurator,
        ):
            workspace_remotes.main([str(target)])
            configurator.return_value.configure_tree.assert_called_once_with(target)
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("config", "--get", "httk.publicRemotes", cwd=target)

    def test_probe_failure_reports_git_reason(self) -> None:
        """Include the anonymous-probe reason in the skip output."""

        repository = self.repository("private")
        self.git(
            "remote", "add", "origin", "git@github.com:httk/private.git", cwd=repository
        )
        with mock.patch("builtins.print") as print_mock:
            workspace_remotes.configure_repository(
                repository,
                probe=lambda url: (
                    False,
                    "fatal: could not read Username for 'https://github.com'",
                ),
            )
        print_mock.assert_any_call(
            f"== {repository}: public probe failed (fatal: could not read Username for "
            "'https://github.com'); skipped"
        )

    def test_probe_redacts_credentials(self) -> None:
        """Redact URL userinfo before exposing a Git diagnostic."""

        with mock.patch(
            "tools.workspace_remotes.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 128, stderr="fatal: https://token:secret@example.invalid/repo"
            ),
        ):
            result = workspace_remotes._probe_public("https://example.invalid/repo")
        self.assertEqual(
            (False, "fatal: https://<redacted>@example.invalid/repo"), result
        )

    def test_probe_has_isolated_git_environment(self) -> None:
        """Remove inherited Git configuration from anonymous probes."""

        completed = subprocess.CompletedProcess([], 0)
        with (
            mock.patch.dict(
                os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_ASKPASS": "/tmp/ask"}
            ),
            mock.patch(
                "tools.workspace_remotes.subprocess.run", return_value=completed
            ) as run,
        ):
            self.assertTrue(
                workspace_remotes.probe_public("https://github.com/httk/example.git")
            )
        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertIn("ls-remote", command)
        self.assertEqual("1", options["env"]["GIT_CONFIG_NOSYSTEM"])
        self.assertEqual("0", options["env"]["GIT_TERMINAL_PROMPT"])
        self.assertNotIn("GIT_CONFIG_COUNT", options["env"])
        self.assertNotEqual(os.getcwd(), options["cwd"])
        self.assertEqual(subprocess.DEVNULL, options["stdin"])
        self.assertEqual(subprocess.PIPE, options["stderr"])


if __name__ == "__main__":
    unittest.main()
