"""Print requirements from the pyproject on stdin that are not yet published.

Each requirement is resolved on its own with ``uv pip compile --no-deps``, so
the output names exactly the internal releases that must be published before
the project can be locked, checked, and tagged. Empty output means every
internal requirement is already published. Only the standard library and ``uv``
are needed. ``--project`` checks the project's exact name and version directly
on PyPI instead; this is the boundary after which its release tag is immutable.
With ``--explain``, failures are printed to stderr.
"""

import json
import re
import subprocess
import sys
import tomllib
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _project_is_on_pypi(name: str, version: str) -> bool:
    """Return whether an exact project version is published on PyPI."""
    url = f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
            json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"PyPI returned HTTP {exc.code} for {name}=={version}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"could not check PyPI for {name}=={version}: {exc}") from exc
    return True


def main() -> int:
    """Resolve each internal requirement and print the unsatisfiable ones."""
    explain = "--explain" in sys.argv[1:]
    project = tomllib.load(sys.stdin.buffer)["project"]
    if "--project" in sys.argv[1:]:
        name = project["name"]
        version = project["version"]
        try:
            published = _project_is_on_pypi(name, version)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
        if not published:
            requirement = f"{name}=={version}"
            if explain:
                print(f"{requirement}: not published on PyPI", file=sys.stderr)
            print(requirement)
        return 0
    requirements = set(project.get("dependencies", ()))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.update(extra)
    internal = sorted(r for r in requirements if re.match(r"httk[-_.]", r, re.IGNORECASE))
    unpublished = []
    for requirement in internal:
        # A dependency may have been published since the preceding release cycle.
        command = ["uv", "pip", "compile", "-", "--no-deps", "--quiet", "--no-header", "--refresh"]
        command += ["--python-version", "3.12", "--python-platform", "linux"]
        try:
            result = subprocess.run(command, input=requirement + "\n", capture_output=True, text=True, check=False)
        except OSError as exc:
            print(f"cannot run uv: {exc}", file=sys.stderr)
            return 2
        if result.returncode != 0:
            # Any resolver failure (unpublished, or index unreachable) defers the
            # release; deferring is the safe direction, so the reason is only logged.
            if explain:
                reason = " ".join(result.stderr.split()).split("Because", 1)[-1].strip()
                print(f"{requirement}: because {reason}", file=sys.stderr)
            unpublished.append(requirement)
    print(" ".join(unpublished))
    return 0


if __name__ == "__main__":
    sys.exit(main())
