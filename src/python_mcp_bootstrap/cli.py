"""Command-line diagnostics for the bootstrap contract."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import PIN, REQUIRED, find_uv, required_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python-mcp-bootstrap",
        description="Inspect the pre-install Python bootstrap contract.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the bootstrap pin and current selection facts as JSON",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the diagnostic CLI.

    This command is intentionally diagnostic: it never invokes uv, pip, or a
    subprocess. Application first-run wrappers call the library API instead.
    """

    parser = _parser()
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 2

    payload = {
        "ok": True,
        "version": __version__,
        "required": f">={required_text(REQUIRED)}",
        "pin": PIN,
        "uv": find_uv(),
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
