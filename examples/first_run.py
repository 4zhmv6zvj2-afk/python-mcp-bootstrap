#!/usr/bin/env python3
"""Minimal first-run wrapper for a Python MCP app.

The core is vendored into ``_vendor/`` by ``scripts/vendor.py`` (see
``docs/integration.md``), the same way a real consumer ships it.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from _vendor.python_mcp_bootstrap import BootstrapSpec, bootstrap
except ModuleNotFoundError as exc:
    if exc.name is None or not exc.name.startswith("_vendor"):
        raise
    print(
        "example-mcp: the vendored core is missing. From the repository root, run:\n"
        "  python scripts/vendor.py --target examples "
        "--dest _vendor/python_mcp_bootstrap.py",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

ROOT = Path(__file__).resolve().parent


def continue_setup(args: list[str]) -> int:
    """Run the rest of setup on the interpreter chosen by bootstrap."""

    print(f"example-mcp: setup complete on Python {sys.version.split()[0]}")
    if args:
        print("example-mcp: forwarded arguments:", " ".join(args))
    return 0


SPEC = BootstrapSpec(
    app="example-mcp",
    entrypoint="first_run.py",
    env_var="EXAMPLE_MCP_INTERPRETER",
    install_args=("-e", "."),
    verify_import="example_mcp",
    package_main=continue_setup,
)


if __name__ == "__main__":
    raise SystemExit(bootstrap(sys.argv[1:], ROOT, SPEC))
