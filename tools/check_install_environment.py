"""Refuse ``make install*`` outside a virtual environment or non-base conda environment."""

import os
import sys
from collections.abc import Mapping

BASE_MESSAGE = (
    "the active conda environment is base; activate a named conda environment "
    "(conda create -n httk python=3.12) or a virtual environment"
)


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def install_environment_problem(
    prefix: str, base_prefix: str, environ: Mapping[str, str]
) -> str | None:
    """Decide whether the interpreter may be installed into.

    :param prefix: ``sys.prefix`` of the interpreter.
    :param base_prefix: ``sys.base_prefix`` of the interpreter.
    :param environ: Environment variables.
    :return: ``None`` if allowed, otherwise the refusal text.
    """
    if prefix != base_prefix:
        return None
    conda = environ.get("CONDA_PREFIX")
    if conda and _same_path(prefix, conda):
        if environ.get("CONDA_DEFAULT_ENV") != "base":
            return None
        problem = BASE_MESSAGE
    else:
        problem = "no activated virtual environment or conda environment"
    return f"{problem} (python: {sys.executable}, prefix: {prefix}, CONDA_PREFIX: {conda or 'unset'})"


def main() -> None:
    """Check the running interpreter; print the problem and exit 1 if refused."""
    problem = install_environment_problem(sys.prefix, sys.base_prefix, os.environ)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
