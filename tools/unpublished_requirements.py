"""Print the ``httk-*`` requirements of the pyproject on stdin that the package index cannot satisfy.

Each requirement is resolved on its own with ``uv pip compile --no-deps``, so
the output names exactly the internal releases that must be published before
the project can be locked, checked, and tagged. Empty output means every
internal requirement is already published. Only the standard library and ``uv``
are needed. With ``--explain``, the resolver's reason for each unsatisfiable
requirement is printed to stderr.
"""

import re
import subprocess
import sys
import tomllib


def main() -> int:
    """Resolve each internal requirement and print the unsatisfiable ones."""
    explain = "--explain" in sys.argv[1:]
    project = tomllib.load(sys.stdin.buffer)["project"]
    requirements = set(project.get("dependencies", ()))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.update(extra)
    internal = sorted(r for r in requirements if re.match(r"httk[-_.]", r, re.IGNORECASE))
    unpublished = []
    for requirement in internal:
        command = ["uv", "pip", "compile", "-", "--no-deps", "--quiet", "--no-header"]
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
