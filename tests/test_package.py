"""Package-level smoke tests."""

from __future__ import annotations

from pathlib import Path

import python_mcp_bootstrap


def test_package_version_is_semver() -> None:
    parts = python_mcp_bootstrap.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_py_typed_is_packaged() -> None:
    package = Path(python_mcp_bootstrap.__file__).parent
    assert (package / "py.typed").is_file()
