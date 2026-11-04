"""Unit tests for the stable bootstrap contract."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from python_mcp_bootstrap import core
from python_mcp_bootstrap.core import (
    CARD,
    PIN,
    REPAIR_CARD,
    REQUIRED,
    UV_INSTALL,
    BootstrapSpec,
    find_uv,
    floor_text,
    format_version,
    required_text,
    venv_python,
    version_tuple,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.15.2", (3, 15, 2)),
        ("Python 3.14.10", (3, 14, 10)),
        (" 3.14 ", (3, 14, 0)),
        ("3", (3, 0, 0)),
        ("3.15.2.post1", (3, 15, 2)),
        ("3.15.2+local", (3, 15, 2)),
    ],
)
def test_version_tuple_parses_supported_text(text: str, expected: tuple[int, int, int]) -> None:
    assert version_tuple(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Python",
        "3..2",
        "v3.15.2",
        None,
        "3.14.0rc1",
        "3.15.2a1",
        "3.15.2b1",
        "3.15.2.dev1",
        "3.15.2-rc1",
    ],
)
def test_version_tuple_rejects_non_versions(text: object) -> None:
    assert version_tuple(text) is None


def test_prerelease_does_not_satisfy_the_floor() -> None:
    assert version_tuple("3.14.0rc1") is None
    assert version_tuple("3.15.2") == (3, 15, 2)


def test_format_and_required_text() -> None:
    assert format_version((3, 14, 10)) == "3.14.10"
    assert required_text(REQUIRED) == "3.14.0"
    assert required_text((3, 15, 2)) == "3.15.2"
    assert floor_text(REQUIRED) == "3.14"
    assert floor_text((3, 14, 10)) == "3.14.10"


def test_spec_defaults_are_the_shared_contract() -> None:
    spec = BootstrapSpec(app="example-mcp")
    assert spec.entrypoint == "first_run.py"
    assert spec.env_var == "MCP_BOOTSTRAP_INTERPRETER"
    assert spec.package_main is None
    assert spec.required == REQUIRED
    assert spec.pin == PIN
    assert spec.install_args == ("-e", ".")
    assert spec.verify_import is None
    assert spec.card == CARD
    assert spec.repair_card == REPAIR_CARD
    assert spec.venv_dir == ".venv"
    assert spec.python_dir == ".uv-python"
    assert spec.pin_file == ".python-version"


def test_spec_default_card_follows_a_pin_override() -> None:
    default = BootstrapSpec(app="example-mcp")
    overridden = BootstrapSpec(app="example-mcp", pin="3.16.1")
    custom = BootstrapSpec(app="example-mcp", pin="3.16.1", card="Continue?")

    assert default.card == CARD
    assert "3.16.1" in overridden.card
    assert "3.15.2" not in overridden.card
    assert custom.card == "Continue?"


def test_spec_rejects_pin_below_required() -> None:
    with pytest.raises(ValueError, match="pin"):
        BootstrapSpec(app="example-mcp", required=(3, 16, 0), pin="3.15.2")
    assert BootstrapSpec(app="example-mcp", required=(3, 15, 0), pin="3.15.2").pin == "3.15.2"


@pytest.mark.parametrize(
    "pin",
    ["3.15.2.post1", "3.15.2+local", "3.15.2.1", "Python 3.15.2", "v3.15.2"],
)
def test_spec_rejects_non_plain_pins(pin: str) -> None:
    with pytest.raises(ValueError, match="pin"):
        BootstrapSpec(app="example-mcp", pin=pin)


def test_spec_accepts_plain_pins() -> None:
    assert BootstrapSpec(app="example-mcp", pin="3.15.2").pin == "3.15.2"
    assert BootstrapSpec(app="example-mcp", pin="3.15").pin == "3.15"


def test_default_card_matches_the_move_aside_behavior() -> None:
    assert "moved aside" in CARD
    assert "Nothing already installed" not in CARD


def test_spec_rejects_empty_app_and_bad_pin() -> None:
    with pytest.raises(ValueError, match="app"):
        BootstrapSpec(app=" ")
    with pytest.raises(ValueError, match="pin"):
        BootstrapSpec(app="example-mcp", pin="main")
    with pytest.raises(ValueError, match="verify_import"):
        BootstrapSpec(app="example-mcp", verify_import="not a module")
    with pytest.raises(ValueError, match="repair_card"):
        BootstrapSpec(app="example-mcp", repair_card=" ")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"entrypoint": " "}, "entrypoint"),
        ({"env_var": " "}, "env_var"),
        ({"venv_dir": " "}, "venv_dir"),
        ({"required": (3,)}, "required"),
    ],
)
def test_spec_rejects_incomplete_paths(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BootstrapSpec(app="example-mcp", **kwargs)  # type: ignore[arg-type]


def test_spec_is_frozen() -> None:
    spec = BootstrapSpec(app="example-mcp")
    with pytest.raises(AttributeError):
        spec.app = "other"  # type: ignore[misc]


def test_venv_python_uses_posix_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "os", SimpleNamespace(name="posix"))
    assert venv_python(Path("/tmp/project")) == Path("/tmp/project/.venv/bin/python")
    assert venv_python(Path("/tmp/project"), "env") == Path("/tmp/project/env/bin/python")


def test_venv_python_uses_windows_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "os", SimpleNamespace(name="nt"))
    assert venv_python(Path("C:/project")) == Path("C:/project/.venv/Scripts/python.exe")


def test_find_uv_prefers_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: "/fake/uv")
    assert find_uv() == "/fake/uv"


def test_core_stays_parseable_on_python_312() -> None:
    source = Path(core.__file__).read_text(encoding="utf-8")
    ast.parse(source, filename=str(core.__file__), feature_version=(3, 12))


def test_core_does_not_import_mcp() -> None:
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "import mcp" not in source
    assert "from mcp" not in source


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("entrypoint", "../run.py", "entrypoint"),
        ("entrypoint", "/etc/passwd", "entrypoint"),
        ("entrypoint", "\\temp\\outside.py", "entrypoint"),
        ("venv_dir", "{absolute}", "venv_dir"),
        ("venv_dir", "\\temp\\outside", "venv_dir"),
        ("python_dir", "../python", "python_dir"),
        ("python_dir", "\\temp\\outside", "python_dir"),
        ("pin_file", "{absolute}", "pin_file"),
        ("pin_file", "\\temp\\outside", "pin_file"),
    ],
)
def test_spec_rejects_paths_outside_the_project(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    if value == "{absolute}":
        value = str(tmp_path / "outside")
    with pytest.raises(ValueError, match=message):
        BootstrapSpec(app="example-mcp", **{field: value})  # type: ignore[arg-type]


def test_spec_rejects_an_invalid_environment_name() -> None:
    with pytest.raises(ValueError, match="env_var"):
        BootstrapSpec(app="example-mcp", env_var="1BAD-NAME")


@pytest.mark.skipif(os.name == "nt", reason="POSIX uv path")
def test_find_uv_falls_back_to_local_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    exe = home / ".local" / "bin" / "uv"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)
    monkeypatch.setattr(core.Path, "home", classmethod(lambda _cls: home))

    assert find_uv() == str(exe)


def test_find_uv_returns_none_when_nothing_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)
    monkeypatch.setattr(core.Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    assert find_uv() is None


def test_verify_command_is_isolated() -> None:
    spec = BootstrapSpec(app="example-mcp", verify_import="example_mcp")
    python = Path("/venv/bin/python")
    command = core._verify_command(python, spec)

    assert command is not None
    assert command[0] == str(python)
    assert command[1:4] == ["-I", "-P", "-c"]
    assert "import_module('example_mcp')" in command[-1]


def test_isolated_verify_still_imports_site_packages(tmp_path: Path) -> None:
    """`-I -P` must not hide the target interpreter's site-packages.

    Editable src-layout installs are ``.pth`` entries in site-packages, so the
    isolation flags must not behave like ``-S``.  ``pytest`` is used because it
    is guaranteed to be installed for the running interpreter.
    """

    spec = BootstrapSpec(app="example-mcp", verify_import="pytest")
    command = core._verify_command(Path(sys.executable), spec)
    assert command is not None

    result = core.run_command(command, tmp_path, dict(os.environ), 60)
    assert result["returncode"] == 0


def test_uv_install_is_a_human_tip_only() -> None:
    assert "docs.astral.sh" in UV_INSTALL
    assert "curl" not in UV_INSTALL.casefold()
    assert "|" not in UV_INSTALL


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",  # Unix absolute: not absolute on Windows, still rooted
        "../outside",
        "tools/../../outside",
        "C:\\outside\\app",  # Windows drive absolute
        "\\temp\\outside",  # Windows rooted, drive-relative
        "--target=/etc/passwd",  # path embedded in a long flag value
        "--target=C:\\outside\\app",
        "--target=../outside",
        "--config-settings=--prefix=/tmp/outside",
        "-t/tmp/outside",  # attached short-option value
        "-tC:\\outside\\app",
        "-t../outside",
        "-e../outside",
        "-f/tmp/outside",
        "-t=/tmp/outside",
        "-vt/tmp/outside",  # clustered short option: -v -t /tmp/outside
        "-vtC:\\outside\\app",
        "-vt../outside",
        "-Ckey=/tmp/outside",
        "--target=dist",  # venv-redirecting long flag with a relative path
        "--target",
        "--prefix=dist",
        "--root=dist",
        "--python=python3",
        "-t",
        "-p",
        "-vt",
    ],
)
def test_spec_rejects_install_args_that_escape_the_project(value: str) -> None:
    with pytest.raises(ValueError, match="install_args"):
        BootstrapSpec(app="example-mcp", install_args=(value,))


def test_spec_allows_short_flag_values_that_stay_local() -> None:
    args = (
        "-e.",
        "-vU",
        "-e",
        ".",
        "-Ckey=value",
        "-f",
        "dist/wheels",
        "-ihttps://user:token@example/simple",
    )
    assert BootstrapSpec(app="example-mcp", install_args=args).install_args == args


def test_spec_allows_credentialed_url_install_args() -> None:
    """A URL is a package source, not a project path; reports redact it."""

    args = ("--index-url=https://user:token@example/simple", "example-mcp")
    assert BootstrapSpec(app="example-mcp", install_args=args).install_args == args


def test_spec_allows_project_local_install_args() -> None:
    args = ("-e", ".", "-U", "dist/example_mcp.whl")
    assert BootstrapSpec(app="example-mcp", install_args=args).install_args == args


def test_spec_rejects_a_bare_string_install_args() -> None:
    with pytest.raises(ValueError, match="install_args"):
        BootstrapSpec(app="example-mcp", install_args="-e .")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "https://user:s3cret@example/simple",
        "ssh://user:s3cret@example/repo",
        "git+ssh://user:s3cret@example/repo",
    ],
)
def test_redact_masks_url_userinfo(text: str) -> None:
    masked = core._redact(text)
    assert "s3cret" not in masked
    assert "***:***@" in masked


def test_core_never_uses_a_shell_or_the_curl_tip() -> None:
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "curl" not in source.casefold()
