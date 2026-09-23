"""Focused filesystem checks for retained documentation preparation evidence."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import release_docs


class ReleaseDocsFilesTest(unittest.TestCase):
    """Exercise cache invalidation and safe snapshot/copyback primitives."""

    def test_cache_reuses_final_input_but_invalidates_changed_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            (repo / ".gitignore").write_text("docs/_build/\n")
            snapshot = Path(temporary) / "snapshot"
            inventory = snapshot / "docs/_build/html/objects.inv"
            inventory.parent.mkdir(parents=True)
            inventory.write_bytes(b"inventory")
            entry = {
                "key": "original",
                "final": "final",
                "final_key": "different",
                "snapshot": str(snapshot),
                "inventories": {"httk-core": "one"},
                "manifest": {},
                "inventory_digest": release_docs.hashlib.sha256(
                    inventory.read_bytes()
                ).hexdigest(),
            }
            self.assertEqual(
                release_docs._cached_snapshot(
                    entry, "different", {"httk-core": "one"}, repo
                ),
                snapshot,
            )
            self.assertIsNone(
                release_docs._cached_snapshot(
                    entry, "different", {"httk-core": "two"}, repo
                )
            )

    def test_snapshot_preserves_modes_links_and_refuses_stale_copyback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            source = repo / "docs/requirements.lock"
            source.parent.mkdir()
            source.write_text("old\n")
            executable = repo / "docs/tool"
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
            link = repo / "docs/current"
            link.symlink_to("requirements.lock")
            subprocess.run(["git", "-C", str(repo), "add", "docs"], check=True)
            target = Path(temporary) / "snapshot"
            release_docs._snapshot(repo, target)
            self.assertEqual((target / "docs/requirements.lock").read_text(), "old\n")
            self.assertTrue((target / "docs/current").is_symlink())
            self.assertTrue((target / "docs/tool").stat().st_mode & 0o111)
            baseline = release_docs._manifest(
                target, release_docs._source_paths(target)
            )
            (target / "docs/requirements.lock").write_text("gate mutation\n")
            with self.assertRaisesRegex(ValueError, "changed exported source files"):
                release_docs._assert_source_unchanged(repo, target, baseline)
            self.assertEqual(source.read_text(), "old\n")

    def test_build_invalidates_previous_success_before_code_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            state.write_text(
                '{"schema": 1, "status": "code-passed", "docs": {"status": "passed"}}\n'
            )
            with (
                mock.patch.object(
                    release_docs, "verify_code", side_effect=ValueError("stale code")
                ),
                self.assertRaisesRegex(ValueError, "stale code"),
            ):
                release_docs.build_docs(state)
            self.assertIn('"status": "failed"', state.read_text())

    def test_module_and_aggregate_are_independent_stages(self) -> None:
        """Each command performs only its own stage and retains module evidence."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "state.json"
            wheels = root / "wheels"
            wheels.mkdir()
            release_docs.save_state(
                state_path,
                {"schema": 1, "status": "code-passed", "wheels": str(wheels)},
            )
            selection = release_docs.Selection(
                "module", root, "abc", "1.0.0", True, "v1.0.0-rc0"
            )
            with (
                mock.patch.object(
                    release_docs, "verify_code", return_value=[selection]
                ),
                mock.patch.object(
                    release_docs,
                    "_candidate_docs",
                    return_value=({"module": {"final": "checked"}}, True),
                ) as modules,
                mock.patch.object(
                    release_docs, "_aggregate", return_value={"repo": "site"}
                ) as aggregate,
                mock.patch.object(release_docs, "_print_groups"),
                mock.patch.object(release_docs, "fingerprint", return_value="checked"),
                mock.patch.object(release_docs, "_clean", return_value=True),
            ):
                release_docs.build_docs(state_path)
                aggregate.assert_not_called()
                self.assertEqual(
                    release_docs.load_state(state_path)["docs"]["status"],
                    "modules-ready",
                )
                release_docs.build_aggregate_docs(state_path, root / "site")
                modules.assert_called_once()
                aggregate.assert_called_once()
                self.assertEqual(
                    release_docs.load_state(state_path)["docs"]["status"], "passed"
                )
                # A changed module fails the aggregate preflight and invalidates
                # aggregate success while retaining the module-stage report.
                with (
                    mock.patch.object(
                        release_docs, "fingerprint", return_value="changed"
                    ),
                    self.assertRaisesRegex(
                        release_docs.DocsError, "module docs changed"
                    ),
                ):
                    release_docs.build_aggregate_docs(state_path, root / "site")
                self.assertEqual(
                    release_docs.load_state(state_path)["docs"]["status"],
                    "aggregate-failed",
                )
                self.assertEqual(
                    release_docs.load_state(state_path)["docs"]["modules_status"],
                    "passed",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
