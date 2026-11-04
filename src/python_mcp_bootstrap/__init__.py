"""Shared, stdlib-only bootstrap for Python MCP applications."""

from __future__ import annotations

from .core import (
    CARD,
    PIN,
    PIN_FILE,
    PYTHON_DIR,
    REPAIR_CARD,
    REQUIRED,
    UV_INSTALL,
    VENV_DIR,
    BootstrapSpec,
    Exec,
    Main,
    Probe,
    Runner,
    bootstrap,
    find_uv,
    floor_text,
    format_version,
    interpreter_version,
    provision,
    required_text,
    run_command,
    venv_python,
    version_tuple,
)

__version__ = "0.1.4"

__all__ = [
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
]
