"""Package-level smoke tests."""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import pytest

import python_mcp_bootstrap

try:
    DISTRIBUTION = importlib.metadata.distribution("python-mcp-bootstrap")
except importlib.metadata.PackageNotFoundError:  # extracted sdist, no install
    DISTRIBUTION = None

requires_distribution = pytest.mark.skipif(
    DISTRIBUTION is None,
    reason="package is not installed (for example in the extracted sdist)",
)

PUBLIC_NAMES = {
    "CARD",
    "PIN",
    "PIN_FILE",
    "PYTHON_DIR",
    "REPAIR_CARD",
    "REQUIRED",
    "UV_INSTALL",
    "VENV_DIR",
    "BootstrapSpec",
    "Exec",
    "Main",
    "Probe",
    "Runner",
    "__version__",
    "bootstrap",
    "find_uv",
    "floor_text",
    "format_version",
    "interpreter_version",
    "provision",
    "required_text",
    "run_command",
    "venv_python",
    "version_tuple",
}


def test_package_version_is_semver() -> None:
    parts = python_mcp_bootstrap.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_py_typed_is_packaged() -> None:
    package = Path(python_mcp_bootstrap.__file__).parent
    assert (package / "py.typed").is_file()


@requires_distribution
def test_distribution_metadata_matches_the_package() -> None:
    assert DISTRIBUTION is not None
    metadata = DISTRIBUTION.metadata
    assert metadata["Name"] == "python-mcp-bootstrap"
    assert DISTRIBUTION.version == python_mcp_bootstrap.__version__
    assert metadata["Requires-Python"] == ">=3.12"
    assert metadata["License-Expression"] == "MIT"
    labels = {entry.split(", ", 1)[0] for entry in metadata.get_all("Project-URL") or []}
    assert {"Repository", "Documentation", "Changelog", "Issues"} <= labels


@requires_distribution
def test_console_script_is_declared() -> None:
    scripts = {
        entry.name: entry.value
        for entry in importlib.metadata.entry_points(group="console_scripts")
    }
    assert scripts.get("python-mcp-bootstrap") == "python_mcp_bootstrap.cli:main"


def test_public_all_covers_the_documented_names() -> None:
    assert set(python_mcp_bootstrap.__all__) == PUBLIC_NAMES
    for name in python_mcp_bootstrap.__all__:
        assert getattr(python_mcp_bootstrap, name) is not None


def test_module_version_smoke() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "python_mcp_bootstrap", "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert python_mcp_bootstrap.__version__ in result.stdout
