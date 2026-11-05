"""Core contract for the pre-install Python bootstrap.

This module is deliberately stdlib-only and importable on Python 3.12.  The
package metadata requires 3.12, and consumers copy this file into a first-run
entry point that may execute before the application's dependencies exist.
A consumer may raise ``BootstrapSpec.required`` to ask for a newer interpreter.
"""

from __future__ import annotations

import json
import keyword
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, cast

Version = tuple[int, int, int]
Main = Callable[[list[str]], int]
Runner = Callable[[list[str], Path, dict[str, str], int], dict[str, Any]]
Probe = Callable[[str], Version | None]
Exec = Callable[[str, list[str], dict[str, str]], int | None]

REQUIRED: Version = (3, 12, 0)
PIN = "3.15.2"
# uv releases before this cannot resolve the pinned managed-Python build.
UV_MIN_FOR_PIN: Version = (0, 13, 0)
VENV_DIR = ".venv"
PYTHON_DIR = ".uv-python"
PIN_FILE = ".python-version"
UV_INSTALL = (
    "uv is not installed. Install it from the official instructions, then "
    "re-run with --install-python: "
    "https://docs.astral.sh/uv/getting-started/installation/"
)
CARD_TEMPLATE = (
    "Set up needs a project-local Python {pin} on this computer (one-time "
    "download). Your system Python is not changed; a mismatched .venv is "
    "moved aside. Continue?"
)
CARD = CARD_TEMPLATE.format(pin=PIN)
REPAIR_CARD = (
    "The project environment is missing the app or MCP. Re-run with "
    "--install-python to repair it. Nothing has been downloaded. Continue?"
)


@dataclass(frozen=True, slots=True)
class BootstrapSpec:
    """Application-specific settings for one bootstrap entry point."""

    app: str
    entrypoint: str = "first_run.py"
    env_var: str = "MCP_BOOTSTRAP_INTERPRETER"
    package_main: Main | None = None
    required: Version = REQUIRED
    pin: str = PIN
    install_args: tuple[str, ...] = ("-e", ".")
    requirements: tuple[str, ...] = ()
    verify_import: str | None = None
    card: str = CARD
    venv_dir: str = VENV_DIR
    python_dir: str = PYTHON_DIR
    pin_file: str = PIN_FILE
    uv_install: str = UV_INSTALL
    repair_card: str = REPAIR_CARD

    def __post_init__(self) -> None:
        if not self.app.strip():
            raise ValueError("app must not be empty")
        if not self.entrypoint.strip():
            raise ValueError("entrypoint must not be empty")
        if not self.env_var.strip():
            raise ValueError("env_var must not be empty")
        if not self.venv_dir.strip() or not self.python_dir.strip() or not self.pin_file.strip():
            raise ValueError("venv_dir, python_dir, and pin_file must not be empty")
        for field, value in (
            ("entrypoint", self.entrypoint),
            ("venv_dir", self.venv_dir),
            ("python_dir", self.python_dir),
            ("pin_file", self.pin_file),
        ):
            _require_project_path(field, value)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.env_var) is None:
            raise ValueError(f"env_var is not a valid environment name: {self.env_var!r}")
        object.__setattr__(self, "required", _spec_required(self.required))
        if re.fullmatch(r"\d+(?:\.\d+){0,2}", self.pin) is None:
            raise ValueError(f"pin must be a plain version: {self.pin!r}")
        pin_version = version_tuple(self.pin)
        if pin_version is None:
            raise ValueError(f"pin is not a version: {self.pin!r}")
        if pin_version < self.required:
            raise ValueError(f"pin {self.pin!r} is older than required {self.required!r}")
        if self.verify_import is not None and not _valid_module(self.verify_import):
            raise ValueError(f"verify_import is not a module: {self.verify_import!r}")
        object.__setattr__(self, "install_args", _spec_install_args(self.install_args))
        object.__setattr__(self, "requirements", _spec_requirements(self.requirements))
        if not self.card.strip():
            raise ValueError("card must not be empty")
        if not self.repair_card.strip():
            raise ValueError("repair_card must not be empty")
        if self.card == CARD and self.pin != PIN:
            object.__setattr__(self, "card", CARD_TEMPLATE.format(pin=self.pin))


def _spec_required(values: object) -> Version:
    """Return ``values`` as a validated version tuple.

    Accepting a list keeps the constructor friendly; storing a tuple keeps the
    frozen dataclass actually immutable after validation.
    """

    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ValueError(f"required is not a version: {values!r}")
    parts = tuple(values)
    if len(parts) != 3 or any(
        not isinstance(part, int) or isinstance(part, bool) for part in parts
    ):
        raise ValueError(f"required is not a version: {values!r}")
    return cast("Version", parts)


def _spec_install_args(values: object) -> tuple[str, ...]:
    """Return ``values`` as a validated, immutable install-argument tuple."""

    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ValueError(f"install_args must be a sequence of strings: {values!r}")
    items = tuple(values)
    _require_project_install_args(items)
    return cast("tuple[str, ...]", items)


def _spec_requirements(values: object) -> tuple[str, ...]:
    """Return hash-pinned requirement-file paths as an immutable tuple.

    Each entry is a project-relative path to a ``uv pip install
    --require-hashes -r`` input.  The project-path guard keeps the
    provisioning command inside the consumer's checkout.
    """

    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ValueError(f"requirements must be a sequence of paths: {values!r}")
    items = tuple(values)
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"requirements must be non-empty paths: {values!r}")
        _require_project_path("requirements", item)
    return cast("tuple[str, ...]", items)


def _valid_module(value: str) -> bool:
    parts = value.split(".")
    return bool(parts) and all(
        part.isidentifier() and not keyword.iskeyword(part) for part in parts
    )


def _escapes_project(value: str) -> bool:
    """True when ``value`` names a path outside the project root.

    ``PureWindowsPath`` is checked on every platform: a Unix-style rooted
    path such as ``/etc/passwd`` is not absolute on Windows and would
    otherwise pass ``Path.is_absolute()``.
    """

    posix = Path(value)
    windows = PureWindowsPath(value)
    return (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
        or ".." in posix.parts
        or ".." in windows.parts
    )


def _require_project_path(field: str, value: str) -> None:
    if _escapes_project(value):
        raise ValueError(f"{field} must stay inside the project: {value!r}")


_RESERVED_LONG_FLAGS = frozenset(
    {
        "--target",
        "--prefix",
        "--root",
        "--python",
        "--system",
        "--break-system-packages",
    }
)
_VALUE_LONG_FLAGS = frozenset(
    {
        "--find-links",
        "--index-url",
        "--extra-index-url",
        "--requirement",
        "--constraint",
        "--config-settings",
        "--only-binary",
        "--no-binary",
        "--upgrade-strategy",
    }
)
_FILE_URL = re.compile(r"(?i)^file(?:\+[a-z0-9.]+)?:")
_RESERVED_SHORT_FLAGS = frozenset({"t", "p"})
_VALUE_SHORT_FLAGS = frozenset({"e", "r", "c", "f", "i", "C"})


def _short_flag_problem(value: str) -> bool:
    """True when a short token redirects the install or embeds a path.

    A cluster such as ``-vt/tmp`` means ``-v -t /tmp``, so checking only the
    first letter is not enough.  Walk the cluster until a value-taking option.
    """

    cluster = value[1:]
    if "://" not in value and ("/" in cluster or "\\" in cluster or ".." in cluster):
        return True
    for char in cluster:
        if char in _RESERVED_SHORT_FLAGS:
            return True
        if char in _VALUE_SHORT_FLAGS:
            return False
    return False


def _require_project_install_args(values: object) -> None:
    """Keep consumer-supplied install arguments inside the project.

    A bare flag is passed through, but a path-like value is rejected whether
    it is a separate entry (``-e ../app``), embedded in a long flag
    (``--find-links=/tmp/wheels``), or attached to a short flag (``-t/tmp``).
    Flags that redirect the install away from the project venv
    (``--target``, ``--prefix``, ``--root``, ``--python`` and their short
    forms) are rejected.  Non-path flags such as ``--index-url=...`` are left
    alone; credentials in them are redacted before reporting.
    """

    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise ValueError(f"install_args must be a sequence of strings: {values!r}")
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"install_args must be strings: {value!r}")
        if _FILE_URL.match(value):
            raise ValueError(f"install_args must not use a local file: URL: {value!r}")
        if value.startswith("-"):
            if value.startswith("--"):
                name = value.split("=", 1)[0]
                if name in _RESERVED_LONG_FLAGS:
                    raise ValueError(f"install_args must not redirect the install: {value!r}")
                if name in _VALUE_LONG_FLAGS and "=" not in value:
                    raise ValueError(f"install_args must pass {name} as {name}=VALUE: {value!r}")
                embedded = value.split("=")[1:]
            else:
                if _short_flag_problem(value):
                    raise ValueError(
                        f"install_args must not redirect or escape the project: {value!r}"
                    )
                embedded = []
            if any(_FILE_URL.match(part) or _escapes_project(part) for part in embedded):
                raise ValueError(f"install_args must stay inside the project: {value!r}")
            continue
        if _escapes_project(value):
            raise ValueError(f"install_args must stay inside the project: {value!r}")


def version_tuple(text: object) -> Version | None:
    """Parse ``3.15.2`` or ``Python 3.15.2`` into a three-part version.

    Pre-release suffixes (``rc``, ``a``, ``b``, ``dev``) return ``None`` so a
    release candidate never satisfies the final-release floor.  A ``.post``
    or ``+local`` suffix is accepted as the same final version.
    """

    raw = str(text).strip()
    if raw.casefold().startswith("python"):
        raw = raw[6:].strip()
    if not raw:
        return None
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)", raw)
    if match is None:
        return None
    major, minor, patch, suffix = match.groups()
    if suffix and not (suffix.startswith("+") or suffix.startswith(".post")):
        return None
    return (int(major), int(minor or 0), int(patch or 0))


def format_version(found: Version) -> str:
    """Render a parsed version as ``major.minor.patch``."""

    return ".".join(str(part) for part in found)


def required_text(required: Version = REQUIRED) -> str:
    """Render the full floor version, including the patch component."""

    return format_version(required)


def floor_text(required: Version = REQUIRED) -> str:
    """Render the human-facing floor, dropping a zero patch component."""

    major, minor, patch = required
    return f"{major}.{minor}" if patch == 0 else format_version(required)


def venv_python(root: Path, venv_dir: str = VENV_DIR) -> Path:
    """The interpreter a project-local venv writes on this platform."""

    if os.name == "nt":
        return Path(root) / venv_dir / "Scripts" / "python.exe"
    return Path(root) / venv_dir / "bin" / "python"


def find_uv() -> str | None:
    """Find uv without installing or downloading anything."""

    found = shutil.which("uv")
    if found:
        return found

    home = Path.home()
    if os.name == "nt":
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
        ]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.extend(
                [
                    Path(local) / "uv" / "uv.exe",
                    Path(local) / "Microsoft" / "WinGet" / "Links" / "uv.exe",
                ]
            )
    else:
        candidates = [
            home / ".local" / "bin" / "uv",
            home / ".cargo" / "bin" / "uv",
        ]

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


_CREDENTIAL_URL = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)\S*@")
_SECRET_FIELD = re.compile(
    r"(?i)([\"']?\b(?:[A-Za-z0-9]+[_-])*"
    r"(?:token|api[_-]?key|password|passwd|secret|private[_-]?key|access[_-]?key)"
    r"(?:[_-][A-Za-z0-9]+)*\b[\"']?)"
    r"(\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|\S+)"
)
_AUTH_HEADER = re.compile(
    r"(?i)\b((?:proxy-)?authorization\s*:\s*(?:basic|bearer|token|digest)\s+)[^\s\"']+"
)
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")


def _redact(text: str) -> str:
    """Mask credentials that a tool may echo into diagnostics.

    Covers URL userinfo (including passwords containing ``/`` or ``@``),
    ``key=value`` / ``"key": "value"`` pairs for credential-shaped names
    (``AWS_SECRET_ACCESS_KEY``, ``MY_API_KEY``, ...), and
    ``Authorization``/``Proxy-Authorization`` headers (Basic, Bearer, Token,
    Digest) plus bare bearer tokens.  Over-redacting is preferred to leaking.
    """

    text = _CREDENTIAL_URL.sub(r"\1***@", text)
    text = _AUTH_HEADER.sub(r"\1***", text)
    text = _BEARER_TOKEN.sub(r"\1***", text)
    return _SECRET_FIELD.sub(r"\1\2***", text)


def run_command(command: list[str], cwd: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    """Run one provisioning step. Never raises for a missing or slow tool."""

    if not command:
        return {"returncode": 2, "stdout": "", "stderr": "empty command"}

    try:
        done = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": 1, "stdout": "", "stderr": _redact(str(exc))[-2000:]}
    return {
        "returncode": done.returncode,
        "stdout": _redact(done.stdout or "")[-2000:],
        "stderr": _redact(done.stderr or "")[-2000:],
    }


def interpreter_version(exe: str | Path) -> Version | None:
    """Version of another interpreter, without importing the application."""

    path = Path(exe)
    if not path.is_file():
        return None
    result = run_command(
        [str(path), "-c", "import sys; print(sys.version.split()[0])"],
        path.parent,
        dict(os.environ),
        30,
    )
    if result.get("returncode") != 0:
        return None
    return version_tuple(result.get("stdout", ""))


def _move_aside(path: Path) -> Path:
    """Keep a venv from another version or a broken run instead of deleting it."""

    backup = path.with_name(path.name + ".previous")
    index = 1
    while backup.exists():
        backup = path.with_name(path.name + f".previous-{index}")
        index += 1
    path.rename(backup)
    return backup


def _verify_command(python: Path, spec: BootstrapSpec) -> list[str] | None:
    module = spec.verify_import
    if module is None:
        return None
    code = f"import importlib; importlib.import_module({module!r})"
    # ``-I`` implies ``-P`` and also drops PYTHONPATH/user site: only the target
    # interpreter's own site-packages may satisfy the import.  Without this, a
    # flat package at the project root imports through the cwd on sys.path, the
    # check passes, and the repair install never runs.
    return [str(python), "-I", "-P", "-c", code]


def _installed(
    python: Path,
    spec: BootstrapSpec,
    root: Path,
    env: dict[str, str],
    run: Runner,
) -> bool:
    command = _verify_command(python, spec)
    if command is None:
        return True
    result = run(command, root, env, 60)
    return result.get("returncode") == 0


def _step(command: list[str], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": [_redact(part) for part in command],
        "returncode": result.get("returncode"),
        "stderr": _redact(str(result.get("stderr", "")))[-2000:],
    }


def _failed(reason: str, spec: BootstrapSpec, **extra: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "app": spec.app,
        "reason": reason,
        "card": spec.card,
    }
    payload.update(extra)
    return payload


def _uv_version(run: Runner, uv: str | None, root: Path, env: dict[str, str]) -> Version | None:
    """Return the installed uv version, or None when it cannot be determined."""

    if uv is None:
        return None
    result = run([uv, "--version"], root, env, 10)
    match = re.search(
        r"(\d+)\.(\d+)\.(\d+)",
        str(result.get("stdout", "")) + str(result.get("stderr", "")),
    )
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _verification_failure(
    python: Path, spec: BootstrapSpec, found: Version, *, override: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "installed": False,
        "app": spec.app,
        "reason": "verify_import_failed",
        "interpreter": str(python),
        "python_version": format_version(found),
        "required": f">={floor_text(spec.required)}",
        "pin": spec.pin,
        "detail": f"cannot import {spec.verify_import!r} from this interpreter",
    }
    if override:
        payload["override"] = True
    return payload


def _needs_install(python: Path, spec: BootstrapSpec, found: Version) -> dict[str, Any]:
    return {
        "ok": False,
        "installed": False,
        "app": spec.app,
        "reason": "needs_install",
        "interpreter": str(python),
        "python_version": format_version(found),
        "required": f">={floor_text(spec.required)}",
        "pin": spec.pin,
        "needs_consent": True,
        "card": spec.repair_card,
        "next": f"python {spec.entrypoint} --install-python",
    }


def provision(
    root: Path,
    spec: BootstrapSpec,
    *,
    uv: str | None = None,
    run: Runner = run_command,
    probe: Probe = interpreter_version,
) -> dict[str, Any]:
    """Provision the pinned interpreter, venv, and application install.

    The caller is responsible for obtaining consent first.  This function never
    prompts and never installs uv; a missing uv is returned as ``needs_uv``.
    """

    root = Path(root)
    uv = uv or find_uv()
    if not uv:
        return _failed("needs_uv", spec, tip=spec.uv_install)

    python = venv_python(root, spec.venv_dir)
    venv_path = root / spec.venv_dir
    env = dict(os.environ)
    env["UV_PYTHON_INSTALL_DIR"] = str(root / spec.python_dir)
    env["UV_PYTHON_DOWNLOADS"] = "automatic"
    env["UV_PYTHON_PREFERENCE"] = "only-managed"
    env["UV_NO_PROGRESS"] = "1"
    steps: list[dict[str, Any]] = []

    need_venv = True
    if python.is_file():
        found = probe(str(python))
        if found and found >= spec.required:
            need_venv = False
            if _installed(python, spec, root, env, run):
                return {
                    "ok": True,
                    "app": spec.app,
                    "reason": None,
                    "interpreter": str(python),
                    "python_version": format_version(found),
                    "ran_install": False,
                    "installed": True,
                    "steps": steps,
                }
        else:
            try:
                _move_aside(venv_path)
            except OSError as exc:
                return _failed("venv_locked", spec, detail=str(exc), steps=steps)
    elif venv_path.exists():
        try:
            _move_aside(venv_path)
        except OSError as exc:
            return _failed("venv_locked", spec, detail=str(exc), steps=steps)

    if need_venv:
        for command, timeout in (
            ([uv, "python", "install", spec.pin], 600),
            ([uv, "venv", spec.venv_dir, "--python", spec.pin, "--seed"], 300),
        ):
            result = run(command, root, env, timeout)
            steps.append(_step(command, result))
            if result.get("returncode") != 0:
                return _failed("provision_failed", spec, steps=steps)

    if spec.requirements:
        requirements_command = [
            uv,
            "pip",
            "install",
            "--require-hashes",
            *[part for requirement in spec.requirements for part in ("-r", requirement)],
            "--python",
            str(python),
        ]
        result = run(requirements_command, root, env, 600)
        steps.append(_step(requirements_command, result))
        if result.get("returncode") != 0:
            return _failed("runtime_requirements_failed", spec, steps=steps)

    install_command = [
        uv,
        "pip",
        "install",
        "--python",
        str(python),
        *(["--no-deps"] if spec.requirements else []),
        *spec.install_args,
    ]
    result = run(install_command, root, env, 600)
    steps.append(_step(install_command, result))
    if result.get("returncode") != 0:
        return _failed("provision_failed", spec, steps=steps)

    verify_command = _verify_command(python, spec)
    if verify_command is not None:
        result = run(verify_command, root, env, 60)
        steps.append(_step(verify_command, result))
        if result.get("returncode") != 0:
            return _failed("provision_failed", spec, steps=steps)

    found = probe(str(python))
    if not found or found < spec.required:
        return _failed("provision_failed", spec, steps=steps, python_version=None)

    # Only a run that installed the pin may advance ``.python-version``.  On a
    # reuse/repair path the existing interpreter is already good, so writing
    # ``spec.pin`` would point a future offline run at an interpreter that was
    # never downloaded.
    if need_venv:
        pin_path = root / spec.pin_file
        wanted = spec.pin + "\n"
        try:
            if not pin_path.is_file() or pin_path.read_text(encoding="utf-8") != wanted:
                temporary = pin_path.with_name(pin_path.name + ".tmp")
                temporary.write_text(wanted, encoding="utf-8")
                os.replace(temporary, pin_path)
        except (OSError, UnicodeError) as exc:
            return _failed("pin_write_failed", spec, detail=str(exc), steps=steps)

    return {
        "ok": True,
        "app": spec.app,
        "reason": None,
        "interpreter": str(python),
        "python_version": format_version(found),
        "ran_install": True,
        "installed": True,
        "steps": steps,
    }


def _report(payload: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return code


def _default_exec(path: str, argv: list[str], env: dict[str, str]) -> int | None:
    """Replace the process on POSIX; wait for the child on Windows."""

    if os.name == "nt":
        return int(subprocess.call(argv, env=env))
    os.execve(path, argv, env)


def _exec(
    exec_fn: Exec,
    python: Path,
    root: Path,
    spec: BootstrapSpec,
    args: list[str],
) -> int:
    """Replace this process with the chosen interpreter, same script and args."""

    env = dict(os.environ)
    env[spec.env_var] = str(python)
    argv = [str(python), str(Path(root) / spec.entrypoint), *args]
    try:
        result = exec_fn(str(python), argv, env)
    except OSError as exc:
        return _report(
            {
                "ok": False,
                "installed": False,
                "app": spec.app,
                "reason": "exec_failed",
                "interpreter": str(python),
                "detail": _redact(str(exc)),
            },
            8,
        )
    return int(result or 0)


def _too_old(found: str | None, spec: BootstrapSpec, **extra: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "installed": False,
        "app": spec.app,
        "reason": "python_too_old",
        "found": found,
        "required": f">={floor_text(spec.required)}",
        "pin": spec.pin,
    }
    payload.update(extra)
    return payload


def _handed_off(spec: BootstrapSpec) -> bool:
    """True when a previous handoff recorded a usable interpreter.

    ``spec.env_var`` is the handoff signal.  A consumer may branch on it and
    continue without calling ``bootstrap()`` again, so the first pass is
    allowed to exec once to set it.  Every later pass sees it set, which is
    what keeps a consumer that does not branch from looping.
    """

    recorded = os.environ.get(spec.env_var, "").strip()
    return bool(recorded) and os.path.isfile(recorded)


def _missing_continuation(spec: BootstrapSpec) -> dict[str, Any]:
    """Report a handoff that has nowhere to continue.

    Reached only after ``spec.env_var`` is already set: the interpreter has
    been chosen, the entry point has been relaunched, and no continuation is
    configured to take over.  Exec'ing again would be the same process with the
    same arguments, so this is an error, not a handoff.
    """

    return {
        "ok": False,
        "installed": False,
        "app": spec.app,
        "reason": "missing_continuation",
        "interpreter": sys.executable,
        "required": f">={floor_text(spec.required)}",
        "pin": spec.pin,
        "env_var": spec.env_var,
        "handed_off": _handed_off(spec),
        "detail": (
            "the running interpreter already meets the floor and no continuation "
            "is configured; pass BootstrapSpec.package_main (or main_fn) so setup "
            "can continue in-process instead of re-executing this entry point"
        ),
    }


def bootstrap(
    args: list[str],
    root: Path,
    spec: BootstrapSpec,
    *,
    exec_fn: Exec | None = None,
    run: Runner = run_command,
    uv: str | None = None,
    probe: Probe = interpreter_version,
    current: Version | None = None,
    main_fn: Main | None = None,
) -> int:
    """Decide which interpreter runs the install, then hand over to it.

    Order: explicit ``--python``, the running interpreter, an existing good
    ``.venv``, then the consent card.  Only a real download needs consent.
    """

    exec_fn = exec_fn or _default_exec
    root = Path(root)
    cleaned: list[str] = []
    override: str | None = None
    consent = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            cleaned.extend(args[index + 1 :])
            break
        if token == "--python":
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                return _report(
                    {
                        "ok": False,
                        "installed": False,
                        "app": spec.app,
                        "reason": "python_flag_missing",
                    },
                    2,
                )
            override = args[index + 1]
            index += 2
            continue
        if token.startswith("--python="):
            value = token.split("=", 1)[1]
            if not value or value.startswith("-"):
                return _report(
                    {
                        "ok": False,
                        "installed": False,
                        "app": spec.app,
                        "reason": "python_flag_missing",
                    },
                    2,
                )
            override = value
            index += 1
            continue
        if token == "--install-python":
            consent = True
            index += 1
            continue
        cleaned.append(token)
        index += 1

    running = (
        current if current is not None else (version_tuple(sys.version.split()[0]) or (0, 0, 0))
    )
    continuation = main_fn or spec.package_main

    if override is not None:
        found = probe(override)
        if not found or found < spec.required:
            return _report(
                _too_old(format_version(found) if found else None, spec, override=True), 3
            )
        override_path = Path(override)
        if spec.verify_import is not None and not _installed(
            override_path, spec, root, dict(os.environ), run
        ):
            return _report(_verification_failure(override_path, spec, found, override=True), 5)
        return _exec(exec_fn, override_path, root, spec, cleaned)

    running_has_app = True
    if running >= spec.required and spec.verify_import is not None:
        running_has_app = _installed(Path(sys.executable), spec, root, dict(os.environ), run)

    if running >= spec.required and running_has_app:
        if continuation is not None:
            os.environ[spec.env_var] = sys.executable
            return continuation(cleaned)
        if _handed_off(spec):
            return _report(_missing_continuation(spec), 7)
        return _exec(exec_fn, Path(sys.executable), root, spec, cleaned)

    python = venv_python(root, spec.venv_dir)
    broken_venv: tuple[Path, Version] | None = None
    if python.is_file():
        found = probe(str(python))
        if found and found >= spec.required:
            if spec.verify_import is None:
                return _exec(exec_fn, python, root, spec, cleaned)
            if _installed(python, spec, root, dict(os.environ), run):
                return _exec(exec_fn, python, root, spec, cleaned)
            broken_venv = (python, found)

    if not consent:
        if broken_venv is not None:
            return _report(_needs_install(broken_venv[0], spec, broken_venv[1]), 6)
        if running >= spec.required and spec.verify_import is not None:
            return _report(_needs_install(Path(sys.executable), spec, running), 6)
        return _report(
            _too_old(
                format_version(running),
                spec,
                needs_consent=True,
                card=spec.card,
                next=f"python {spec.entrypoint} --install-python",
            ),
            3,
        )

    provisioned = provision(root, spec, uv=uv, run=run, probe=probe)
    if not provisioned.get("ok"):
        payload = dict(provisioned)
        payload["installed"] = False
        code = 4 if provisioned.get("reason") == "needs_uv" else 5
        if provisioned.get("reason") == "provision_failed":
            found_uv = uv or find_uv()
            version = _uv_version(run, found_uv, root, dict(os.environ))
            if version is not None and version < UV_MIN_FOR_PIN:
                payload["tip"] = (
                    f"installed uv reports {format_version(version)}, which may not resolve "
                    "the pinned Python build. Run `uv self update`, or pass --python with an "
                    "interpreter that is already installed."
                )
        return _report(payload, code)
    return _exec(exec_fn, Path(str(provisioned["interpreter"])), root, spec, cleaned)
