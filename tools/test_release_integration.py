"""Opt-in real uv/Python/Sphinx acceptance of the batch coordinator.

Run ``HTTK_RELEASE_INTEGRATION=1 python3 -m unittest tools.test_release_integration``.
Uses temporary repositories and local remotes; never publishes a real release.
Requires the normal workspace checkout of ``modules/httk-core`` and network
access to install test tools and the three supported Python interpreters.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import release_batch, release_docs


@unittest.skipUnless(
    os.environ.get("HTTK_RELEASE_INTEGRATION") == "1", "opt-in real release integration"
)
class RealBatchTests(unittest.TestCase):
    """Exercise real dependency resolution, strict cross-links and docs reuse."""

    def command(self, cwd: Path, *args: str) -> str:
        """Run a fixture command without inheriting signing or hook settings."""
        env = os.environ.copy()
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        result = subprocess.run(
            args, cwd=cwd, env=env, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def repository(self, path: Path, branch: str = "develop") -> None:
        """Initialize a local fixture with a deterministic unsigned identity."""
        path.mkdir(parents=True)
        self.command(path, "git", "init", "-b", branch)
        self.command(path, "git", "config", "user.name", "Release fixture")
        self.command(path, "git", "config", "user.email", "fixture@example.invalid")
        (path / ".gitignore").write_text(
            "__pycache__/\n*.egg-info/\nbuild/\ndist/\ndocs/_build/\n"
        )

    def commit(self, path: Path, title: str) -> str:
        """Commit fixture files and return their new revision."""
        self.command(path, "git", "add", ".")
        self.command(path, "git", "-c", "commit.gpgSign=false", "commit", "-m", title)
        return self.command(path, "git", "rev-parse", "HEAD")

    def module(self, path: Path, name: str, core_source: Path | None = None) -> None:
        """Create a tiny installable module using real shared docs tooling."""
        self.repository(path)
        (path / "README.md").write_text(
            f"# {name}\n\nBatch release integration fixture.\n"
        )
        dependency = '"httk-core==9.8.0"' if name == "httk-sample" else ""
        (path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools>=77", "wheel"]\nbuild-backend = "setuptools.build_meta"\n'
            f'[project]\nname = "{name}"\nversion = "9.8.0"\n'
            'description = "Release integration fixture"\nreadme = "README.md"\nrequires-python = ">=3.12"\n'
            f"dependencies = [{dependency}]\n"
            '[project.optional-dependencies]\ndev = []\ndefault = []\ndocs = ["sphinx>=8"]\n'
            '[tool.setuptools.packages.find]\nwhere = ["src"]\n'
            '[tool.setuptools.package-data]\n"httk.core.docs" = ["assets/*"]\n'
        )
        if core_source is not None:
            shutil.copytree(
                core_source,
                path / "src",
                ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
            )
        else:
            package = path / "src/httk" / name.removeprefix("httk-")
            package.mkdir(parents=True)
            (package / "__init__.py").write_text('"""A batch fixture."""\nVALUE = 42\n')
        (path / "Makefile").write_text(
            'PYTHON ?= python3\n.PHONY: ci docs\nci:\n\t$(PYTHON) -c "import httk.core; assert 6 * 7 == 42"\n'
            "docs:\n\t$(PYTHON) -m sphinx -E -a -W --keep-going -b html docs docs/_build/html\n"
        )
        docs = path / "docs"
        docs.mkdir()
        (docs / "conf.py").write_text(
            f'project = "{name}"\nextensions = ["sphinx.ext.intersphinx", "httk.core.docs.sphinx_ext"]\n'
            'master_doc = "index"\nhtml_theme = "alabaster"\nnitpicky = True\n'
            + (
                'intersphinx_mapping = {"httk-core": ("https://docs.httk.org/httk-core/", "_inventories/httk-core.inv")}\n'
                if name == "httk-sample"
                else ""
            )
        )
        (docs / "index.rst").write_text(
            "Fixture\n=======\n\n"
            + (
                "See :class:`batch_fixture.CoreValue`.\n"
                if name == "httk-sample"
                else ".. py:class:: batch_fixture.CoreValue\n\n   An inventory target.\n"
            )
        )
        (docs / "versioning.toml").write_text(
            f'[site]\nslug = "{name}"\nrepository-url = "https://example.invalid/{name}"\n'
            f'main-branch = "main"\nimport-roots = ["httk/{name.removeprefix("httk-")}"]\n'
            + (
                '\n[[internal-dependency]]\ndistribution = "httk-core"\nslug = "httk-core"\n'
                'repository-url = "https://example.invalid/httk-core"\nmain-branch = "main"\n'
                if name == "httk-sample"
                else ""
            )
        )
        self.commit(path, "Fixture source")
        self.command(path, "git", "branch", "main")
        tag = "v9.8.0" if name == "httk-stable" else "v9.8.0-rc0"
        self.command(path, "git", "tag", tag)

    def site(self, path: Path, modules: Path, names: list[str]) -> None:
        """Create an aggregate with real Git submodules and ecosystem commands."""
        self.repository(path, "main")
        (path / "README.md").write_text("# Fixture site\n")
        (path / "pyproject.toml").write_text(
            '[build-system]\nrequires = ["setuptools>=77", "wheel"]\nbuild-backend = "setuptools.build_meta"\n'
            '[project]\nname = "httk-fixture-site"\nversion = "9.8.0"\nrequires-python = ">=3.12"\n'
            '[project.optional-dependencies]\ndocs = ["sphinx>=8"]\n[tool.setuptools]\npackages = []\n'
        )
        docs = path / "docs"
        docs.mkdir()
        (docs / "conf.py").write_text('project = "fixture"\nmaster_doc = "index"\n')
        (docs / "index.rst").write_text("Aggregate fixture\n=================\n")
        (docs / "versioning.toml").write_text(
            '[site]\nslug = ""\nrepository-url = "https://example.invalid/site"\n'
            'main-branch = "main"\nimport-roots = []\n'
        )
        (path / "Makefile").write_text(
            "PYTHON ?= python3\n"
            "ecosystem-manifest-release:\n\t$(PYTHON) -m httk.core.docs ecosystem-manifest "
            "--submodules-dir submodules --out docs/ecosystem.json --require-release-tags\n"
            "docs-lock:\n\t$(PYTHON) -m httk.core.docs lock .\n"
            'first-use-check:\n\t$(PYTHON) -c "import httk.sample; assert httk.sample.VALUE == 42"\n'
            "docs-full:\n\t$(PYTHON) -m sphinx -E -a -W --keep-going -b html docs docs/_build/html\n"
        )
        scripts = path / "scripts"
        scripts.mkdir()
        (scripts / "check_lock_members.py").write_text(
            '"""Fixture has no external runtime dependencies."""\n'
        )
        (scripts / "verify_topology.py").write_text(
            "import json\nfrom pathlib import Path\n"
            'assert len(json.loads(Path("docs/ecosystem.json").read_text())["modules"]) == 3\n'
        )
        for name in names:
            self.command(
                path,
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(modules / name),
                f"submodules/{name}",
            )
        self.commit(path, "Aggregate fixture")

    def test_real_matrix_and_docs(self) -> None:
        """Unpublished siblings resolve together and link to exact final URLs."""
        core_source = Path(__file__).resolve().parents[1] / "modules/httk-core/src"
        self.assertTrue(
            core_source.is_dir(),
            "initialize modules/httk-core before running acceptance",
        )
        root = Path(tempfile.mkdtemp(prefix="httk-batch-integration-"))
        print(f"Real batch integration retained at {root}", flush=True)
        modules = root / "modules"
        names = ["httk-core", "httk-sample", "httk-stable"]
        for name in names:
            self.module(
                modules / name, name, core_source if name == "httk-core" else None
            )
        site = modules / "httk.github.io"
        self.site(site, modules, names)
        state_path = root / "state.json"
        selected = release_batch.select_modules(modules, names)
        state = release_batch.check_batch(selected, state_path)
        self.assertEqual(state["status"], "code-passed")
        self.assertFalse((modules / "httk-core/docs/_build").exists())
        release_docs.build_docs(state_path, "https://docs.httk.org")
        state = release_batch.load_state(state_path)
        self.assertEqual(state["docs"]["status"], "modules-ready")
        lock = (modules / "httk-sample/docs/requirements.lock").read_text()
        self.assertIn("httk-core==9.8.0", lock)
        self.assertNotIn("file://", lock)
        self.assertIn(
            b"# Version: 9.8.0",
            (modules / "httk-sample/docs/_inventories/httk-core.inv").read_bytes(),
        )
        sample_docs = Path(state["docs"]["builds"]["httk-sample"]["snapshot"])
        self.assertIn(
            "https://docs.httk.org/httk-core/v9.8.0/index.html#batch_fixture.CoreValue",
            (sample_docs / "docs/_build/html/index.html").read_text(),
        )
        for name in names[:2]:
            self.commit(modules / name, "Verified documentation inputs")
        release_docs.build_aggregate_docs(state_path, site, "https://docs.httk.org")
        final = release_batch.load_state(state_path)
        self.assertEqual(final["docs"]["status"], "passed")
        for name in names[:2]:
            self.assertFalse(
                (
                    Path(final["docs"]["aggregate_work"])
                    / "logs"
                    / f"{name}-sphinx.log"
                ).exists(),
                "committing unchanged generated docs must reuse the successful build",
            )
        manifest = json.loads((site / "docs/ecosystem.json").read_text())
        for name in names:
            self.assertEqual(
                manifest["modules"][name]["commit"],
                self.command(modules / name, "git", "rev-parse", "HEAD"),
            )
        # A docs-only commit keeps the checked rc0 identity; code cannot drift.
        release_batch.verify_code(final)
        (modules / "httk-sample/src/httk/sample/__init__.py").write_text("VALUE = 43\n")
        with self.assertRaisesRegex(ValueError, "code inputs changed"):
            release_batch.verify_code(final)


if __name__ == "__main__":
    unittest.main()
