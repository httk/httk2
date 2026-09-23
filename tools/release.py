"""Coordinate code checks, documentation preparation and batch publication."""

import argparse
import subprocess
import sys
from pathlib import Path

from tools import release_batch


def main() -> int:
    """Run one release phase and report a failed gate without publishing further."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path(".release-batch.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check", help="Check the selected batch without building docs."
    )
    check.add_argument("--modules-dir", type=Path, default=Path("modules"))
    check.add_argument("--modules", nargs="+", required=True)
    docs = commands.add_parser(
        "docs", help="Prepare strict version-pinned documentation."
    )
    docs.add_argument("--base-url", default="https://docs.httk.org")
    aggregate = commands.add_parser(
        "aggregate-docs", help="Prepare aggregate docs after module commits."
    )
    aggregate.add_argument("--site", type=Path, default=Path("modules/httk.github.io"))
    aggregate.add_argument("--base-url", default="https://docs.httk.org")
    publish = commands.add_parser(
        "publish", help="Sign and push the verified module releases."
    )
    publish.add_argument("--user-name", required=True)
    publish.add_argument("--user-email", required=True)
    args = parser.parse_args()
    state_path = args.state.resolve()
    try:
        if args.command == "check":
            # Invalidate before selection too: a moved or malformed tag must not
            # leave the preceding successful batch available for publication.
            release_batch.save_state(state_path, {"schema": 1, "status": "checking"})
            selections = release_batch.select_modules(
                args.modules_dir.resolve(), args.modules
            )
            release_batch.check_batch(selections, state_path)
        elif args.command == "docs":
            from tools.release_docs import build_docs

            build_docs(state_path, args.base_url)
        elif args.command == "aggregate-docs":
            from tools.release_docs import build_aggregate_docs

            build_aggregate_docs(state_path, args.site.resolve(), args.base_url)
        else:
            from tools.release_publish import publish

            publish(state_path, args.user_name, args.user_email)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Release stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
