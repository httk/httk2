"""Tests for the install-environment check."""

import tempfile
import unittest

from check_install_environment import install_environment_problem as problem


class InstallEnvironmentTests(unittest.TestCase):
    def test_venv_allowed(self):
        self.assertIsNone(problem("/venv", "/usr", {}))

    def test_named_conda_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                problem(d, d, {"CONDA_PREFIX": d, "CONDA_DEFAULT_ENV": "httk"})
            )

    def test_conda_base_refused(self):
        with tempfile.TemporaryDirectory() as d:
            msg = problem(d, d, {"CONDA_PREFIX": d, "CONDA_DEFAULT_ENV": "base"})
        self.assertIn("is base", msg)

    def test_stale_conda_prefix_refused(self):
        msg = problem(
            "/usr", "/usr", {"CONDA_PREFIX": "/nonexistent/x", "CONDA_DEFAULT_ENV": "x"}
        )
        self.assertIn("no activated", msg)

    def test_nothing_active_refused(self):
        self.assertIn("CONDA_PREFIX: unset", problem("/usr", "/usr", {}))


if __name__ == "__main__":
    unittest.main()
