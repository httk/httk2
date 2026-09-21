"""Tests for the release publication checks."""

import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from tools import unpublished_requirements


class ProjectPublicationTests(unittest.TestCase):
    """Check the exact-version PyPI publication boundary."""

    @patch.object(unpublished_requirements, "urlopen", return_value=io.BytesIO(b"{}"))
    def test_published_exact_version(self, urlopen) -> None:
        """A valid exact-version response marks the tag as published."""
        self.assertTrue(unpublished_requirements._project_is_on_pypi("httk-serve", "2.1.3"))
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://pypi.org/pypi/httk-serve/2.1.3/json",
        )

    @patch.object(unpublished_requirements, "urlopen")
    def test_missing_exact_version(self, urlopen) -> None:
        """A 404 keeps the release tag provisional."""
        urlopen.side_effect = HTTPError("url", 404, "not found", {}, None)
        self.assertFalse(unpublished_requirements._project_is_on_pypi("httk-workflow", "2.1.1"))


if __name__ == "__main__":
    unittest.main()
