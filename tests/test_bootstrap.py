"""Selection, consent, provisioning, and handoff tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from python_mcp_bootstrap import core
from python_mcp_bootstrap.core import (
    CARD,
    REPAIR_CARD,
    BootstrapSpec,
    bootstrap,
    interpreter_version,
    provision,
    venv_python,
)


class ExecRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], dict[str, str]]] = []

    def __call__(self, path: str, argv: list[str], env: dict[str, str]) -> None:
        self.calls.append((path, list(argv), dict(env)))


class RunRecorder:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str], int]] = []
        self.failures = failures or set()

    def __call__(
        self, command: list[str], cwd: Path, env: dict[str, str], timeout: int
    ) -> dict[str, Any]:
        self.calls.append((list(command), cwd, dict(env), timeout))
        if any(needle in " ".join(command) for needle in self.failures):
            return {"returncode": 1, "stdout": "", "stderr": "failed"}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    @property
    def commands(self) -> list[str]:
        return [" ".join(call[0]) for call in self.calls]


class UvVersionRunner(RunRecorder):
    """Report a uv version for --version and fail every other command."""

    def __init__(self, version: str) -> None:
        super().__init__()
        self.version = version

    def __call__(
        self, command: list[str], cwd: Path, env: dict[str, str], timeout: int
    ) -> dict[str, Any]:
        if command[1:] == ["--version"]:
            return {"returncode": 0, "stdout": f"uv {self.version}\n", "stderr": ""}
        return {"returncode": 1, "stdout": "", "stderr": "No download found"}


class ScriptedRunner(RunRecorder):
    def __init__(self, returncodes: list[int]) -> None:
        super().__init__()
        self.returncodes = list(returncodes)

    def __call__(
        self, command: list[str], cwd: Path, env: dict[str, str], timeout: int
    ) -> dict[str, Any]:
        result = super().__call__(command, cwd, env, timeout)
        code = self.returncodes.pop(0) if self.returncodes else 0
        result["returncode"] = code
        result["stderr"] = "" if code == 0 else "failed"
        return result


def _spec(**overrides: Any) -> BootstrapSpec:
    values: dict[str, Any] = {
        "app": "example-mcp",
        "entrypoint": "first_run.py",
        "env_var": "EXAMPLE_MCP_INTERPRETER",
        "install_args": ("-e", "."),
        "verify_import": "example_mcp",
    }
    values.update(overrides)
    return BootstrapSpec(**values)


def _fake_venv(root: Path, spec: BootstrapSpec) -> Path:
    python = venv_python(root, spec.venv_dir)
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    return python


def test_python_override_that_cannot_import_the_app_fails_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The --python branch must not hand off to an interpreter lacking the app."""

    spec = _spec()
    execs = ExecRecorder()

    code = bootstrap(
        ["--python", "/opt/other-python"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=ScriptedRunner([1]),
        current=(3, 14, 10),
        probe=lambda _exe: (3, 15, 2),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 5
    assert report["reason"] == "verify_import_failed"
    assert report["override"] is True
    assert report["interpreter"] == str(Path("/opt/other-python"))
    assert execs.calls == []


def test_running_interpreter_without_the_app_asks_to_repair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A good-enough interpreter missing the app gets the repair card, not success."""

    spec = _spec()
    execs = ExecRecorder()

    code = bootstrap(
        [],
        tmp_path,
        spec,
        exec_fn=execs,
        run=ScriptedRunner([1]),
        current=(3, 14, 10),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 6
    assert report["reason"] == "needs_install"
    assert report["card"] == REPAIR_CARD
    assert report["interpreter"] == sys.executable
    assert execs.calls == []


def test_exec_oserror_becomes_a_json_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A vanished interpreter must produce a report, never a traceback."""

    spec = _spec(verify_import=None)

    def raising_exec(_path: str, _argv: list[str], _env: dict[str, str]) -> None:
        raise OSError("interpreter vanished")

    code = bootstrap([], tmp_path, spec, exec_fn=raising_exec, current=(3, 14, 10))

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 8
    assert report["reason"] == "exec_failed"
    assert "interpreter vanished" in report["detail"]
    assert "Traceback" not in captured.err


def test_old_uv_failure_includes_an_upgrade_tip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = bootstrap(
        ["--install-python"],
        tmp_path,
        _spec(),
        run=UvVersionRunner("0.11.27"),
        current=(3, 12, 13),
        probe=lambda _exe: None,
        uv="/fake/uv",
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 5
    assert report["reason"] == "provision_failed"
    assert "0.11.27" in report["tip"]
    assert "uv self update" in report["tip"]


def test_recent_uv_failure_has_no_upgrade_tip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = bootstrap(
        ["--install-python"],
        tmp_path,
        _spec(),
        run=UvVersionRunner("0.13.7"),
        current=(3, 12, 13),
        probe=lambda _exe: None,
        uv="/fake/uv",
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 5
    assert "tip" not in report


def test_below_floor_without_consent_stops_before_any_subprocess(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    execs = ExecRecorder()
    runs = RunRecorder()

    code = bootstrap(
        [],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        current=(3, 12, 13),
        probe=lambda _exe: None,
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 3
    assert report["reason"] == "python_too_old"
    assert report["app"] == "example-mcp"
    assert report["found"] == "3.12.13"
    assert report["required"] == ">=3.14"
    assert report["needs_consent"] is True
    assert report["card"] == CARD
    assert report["next"] == "python first_run.py --install-python"
    assert execs.calls == []
    assert runs.calls == []


def test_existing_good_venv_is_used_without_a_card(tmp_path: Path) -> None:
    spec = _spec()
    python = _fake_venv(tmp_path, spec)
    execs = ExecRecorder()
    runs = RunRecorder()

    code = bootstrap(
        ["--verbose"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    assert code == 0
    assert len(runs.calls) == 1
    assert len(execs.calls) == 1
    path, argv, env = execs.calls[0]
    assert path == str(python)
    assert argv[1] == str(tmp_path / "first_run.py")
    assert "--verbose" in argv
    assert env["EXAMPLE_MCP_INTERPRETER"] == str(python)


def test_consent_provisions_project_local_python(tmp_path: Path) -> None:
    spec = _spec()
    execs = ExecRecorder()
    runs = RunRecorder()

    code = bootstrap(
        ["--install-python", "--verbose"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        uv="/fake/uv",
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    assert code == 0
    joined = runs.commands
    assert any("python install 3.15.2" in line for line in joined)
    assert any("venv .venv --python 3.15.2 --seed" in line for line in joined)
    assert any("pip install --python" in line and "-e ." in line for line in joined)
    assert any("example_mcp" in line for line in joined)
    assert (tmp_path / ".python-version").read_text(encoding="utf-8") == "3.15.2\n"
    assert execs.calls[0][0] == str(venv_python(tmp_path, spec.venv_dir))

    install_call = next(call for call in runs.calls if "pip install" in " ".join(call[0]))
    command = install_call[0]
    assert command.index("--python") < command.index("-e")
    assert install_call[2]["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / ".uv-python")
    assert install_call[2]["UV_PYTHON_DOWNLOADS"] == "automatic"
    assert install_call[2]["UV_PYTHON_PREFERENCE"] == "only-managed"


def test_consent_without_uv_returns_the_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    monkeypatch.setattr(core, "find_uv", lambda: None)
    execs = ExecRecorder()
    runs = RunRecorder()

    code = bootstrap(
        ["--install-python"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        current=(3, 9, 6),
        probe=lambda _exe: None,
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 4
    assert report["reason"] == "needs_uv"
    assert report["app"] == "example-mcp"
    assert report["tip"] == spec.uv_install
    assert "docs.astral.sh" in report["tip"]
    assert "curl" not in report["tip"]
    assert "|" not in report["tip"]
    assert report["installed"] is False
    assert execs.calls == []
    assert runs.calls == []


def test_python_override_is_checked_before_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    execs = ExecRecorder()

    code = bootstrap(
        ["--python", "/fake/python3.9"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=RunRecorder(),
        current=(3, 12, 13),
        probe=lambda _exe: (3, 9, 6),
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 3
    assert report["override"] is True
    assert execs.calls == []

    code = bootstrap(
        ["--python=/fake/python3.16"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=RunRecorder(),
        current=(3, 12, 13),
        probe=lambda _exe: (3, 16, 0),
    )
    assert code == 0
    assert execs.calls[0][0] == str(Path("/fake/python3.16"))


def test_python_flag_without_a_value_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = bootstrap(["--python"], tmp_path, _spec(), current=(3, 12, 13))
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["reason"] == "python_flag_missing"
    assert report["app"] == "example-mcp"


def test_a_good_running_python_calls_the_continuation(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def main(args: list[str]) -> int:
        seen.append(args)
        return 0

    spec = _spec(package_main=main)
    code = bootstrap(["--verbose"], tmp_path, spec, run=RunRecorder(), current=(3, 14, 10))
    assert code == 0
    assert seen == [["--verbose"]]


def test_in_process_continuation_sets_the_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def main(args: list[str]) -> int:
        del args
        seen.append(os.environ.get("EXAMPLE_MCP_INTERPRETER"))
        return 0

    spec = _spec(package_main=main)
    monkeypatch.setenv("EXAMPLE_MCP_INTERPRETER", "before")
    code = bootstrap([], tmp_path, spec, run=RunRecorder(), current=(3, 14, 10))
    assert code == 0
    assert seen == [sys.executable]


def test_existing_good_venv_with_missing_module_installs_into_it(tmp_path: Path) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)
    runner = ScriptedRunner([1, 0, 0])

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is True
    assert result["app"] == "example-mcp"
    assert result["ran_install"] is True
    assert any("pip install" in command for command in runner.commands)
    assert not any("venv .venv" in command for command in runner.commands)
    assert len(result["steps"]) == 2


def test_wrong_venv_is_moved_aside_not_deleted(tmp_path: Path) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)
    probes: list[str] = []

    def probe(_exe: str) -> tuple[int, int, int]:
        probes.append(_exe)
        return (3, 9, 6) if len(probes) == 1 else (3, 15, 2)

    result = provision(tmp_path, spec, uv="/fake/uv", run=RunRecorder(), probe=probe)

    assert result["ok"] is True
    assert (tmp_path / ".venv.previous").is_dir()


def test_provision_failure_is_reported_without_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    execs = ExecRecorder()
    runs = RunRecorder(failures={"python install"})

    code = bootstrap(
        ["--install-python"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        uv="/fake/uv",
        current=(3, 12, 13),
        probe=lambda _exe: None,
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 5
    assert report["reason"] == "provision_failed"
    assert report["app"] == "example-mcp"
    assert report["installed"] is False
    assert report["steps"]
    assert execs.calls == []


def test_verify_failure_is_reported_without_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    execs = ExecRecorder()
    runs = RunRecorder(failures={"example_mcp"})

    code = bootstrap(
        ["--install-python"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runs,
        uv="/fake/uv",
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 5
    assert report["reason"] == "provision_failed"
    assert execs.calls == []
    assert any("example_mcp" in " ".join(step["command"]) for step in report["steps"])


def test_stale_pin_is_updated(tmp_path: Path) -> None:
    spec = _spec()
    (tmp_path / ".python-version").write_text("3.14.10\n", encoding="utf-8")

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is True
    assert (tmp_path / ".python-version").read_text(encoding="utf-8") == "3.15.2\n"


def test_paths_with_spaces_are_passed_as_arguments(tmp_path: Path) -> None:
    root = tmp_path / "project with spaces and café"
    root.mkdir()
    spec = _spec()
    python = _fake_venv(root, spec)
    execs = ExecRecorder()

    code = bootstrap(
        [],
        root,
        spec,
        exec_fn=execs,
        run=RunRecorder(),
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    assert code == 0
    assert execs.calls[0][1][0] == str(python)
    assert "project with spaces and café" in execs.calls[0][1][0]


def test_custom_floor_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = _spec(required=(3, 15, 0))
    code = bootstrap([], tmp_path, spec, current=(3, 14, 10))
    report = json.loads(capsys.readouterr().out)
    assert code == 3
    assert report["required"] == ">=3.15"


@pytest.mark.skipif(os.name == "nt", reason="POSIX probe script")
def test_interpreter_version_probes_an_executable(tmp_path: Path) -> None:
    exe = tmp_path / "python"
    exe.write_text("#!/bin/sh\nprintf '3.15.2\\n'\n", encoding="utf-8")
    exe.chmod(0o755)
    assert interpreter_version(exe) == (3, 15, 2)


@pytest.mark.skipif(os.name == "nt", reason="POSIX probe script")
def test_interpreter_version_rejects_a_prerelease(tmp_path: Path) -> None:
    exe = tmp_path / "python"
    exe.write_text("#!/bin/sh\nprintf '3.14.0rc1\\n'\n", encoding="utf-8")
    exe.chmod(0o755)
    assert interpreter_version(exe) is None


def test_existing_good_venv_without_an_import_check_is_ready(tmp_path: Path) -> None:
    spec = _spec(verify_import=None)
    _fake_venv(tmp_path, spec)
    runner = RunRecorder()

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is True
    assert result["ran_install"] is False
    assert result["steps"] == []
    assert runner.calls == []


def test_venv_locked_is_reported_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)

    def locked(_path: Path) -> Path:
        raise OSError("locked")

    monkeypatch.setattr(core, "_move_aside", locked)
    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 9, 6),
    )

    assert result["ok"] is False
    assert result["reason"] == "venv_locked"
    assert (tmp_path / ".venv").is_dir()


def test_pip_failure_stops_before_verification(tmp_path: Path) -> None:
    spec = _spec()
    runner = RunRecorder(failures={"pip install"})

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    assert result["reason"] == "provision_failed"
    assert not any("example_mcp" in command for command in runner.commands)
    assert (tmp_path / ".python-version").exists() is False


def test_pin_write_failure_is_reported(tmp_path: Path) -> None:
    spec = _spec(pin_file="missing/pin")
    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    assert result["reason"] == "pin_write_failed"


def test_run_command_reports_a_missing_tool(tmp_path: Path) -> None:
    result = core.run_command([str(tmp_path / "missing")], tmp_path, {}, 1)
    assert result["returncode"] != 0
    assert result["stderr"]


def test_run_command_replaces_undecodable_output(tmp_path: Path) -> None:
    script = "import sys; sys.stdout.buffer.write(b'\\xff')"
    result = core.run_command([sys.executable, "-c", script], tmp_path, {}, 5)
    assert result["returncode"] == 0
    assert "\ufffd" in result["stdout"]


def test_interpreter_version_rejects_a_missing_file(tmp_path: Path) -> None:
    assert interpreter_version(tmp_path / "missing") is None


def test_broken_venv_directory_is_moved_aside(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    result = provision(
        tmp_path,
        _spec(),
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is True
    assert (tmp_path / ".venv.previous").is_dir()


def test_venv_creation_failure_stops_before_install(tmp_path: Path) -> None:
    runner = RunRecorder(failures={"venv .venv"})
    result = provision(
        tmp_path,
        _spec(),
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    assert result["reason"] == "provision_failed"
    assert len(result["steps"]) == 2
    assert not any("pip install" in command for command in runner.commands)


def test_double_dash_stops_bootstrap_flag_parsing(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def main(args: list[str]) -> int:
        seen.append(args)
        return 0

    spec = _spec(package_main=main)
    code = bootstrap(
        ["--", "--install-python", "--python", "not-a-flag"],
        tmp_path,
        spec,
        run=RunRecorder(),
        current=(3, 14, 10),
    )

    assert code == 0
    assert seen == [["--install-python", "--python", "not-a-flag"]]


@pytest.mark.parametrize(
    "args",
    [["--python="], ["--python", "--install-python"], ["--python", "-x"], ["--python=-x"]],
)
def test_incomplete_python_override_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    code = bootstrap(args, tmp_path, _spec(), current=(3, 12, 13))
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["reason"] == "python_flag_missing"
    assert report["app"] == "example-mcp"


def test_no_consent_never_looks_for_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected() -> str | None:
        raise AssertionError("find_uv must not run without consent")

    monkeypatch.setattr(core, "find_uv", unexpected)
    code = bootstrap([], tmp_path, _spec(), current=(3, 12, 13), probe=lambda _exe: None)
    assert code == 3
    assert json.loads(capsys.readouterr().out)["reason"] == "python_too_old"


def test_default_exec_uses_subprocess_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(core, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        core.subprocess,
        "call",
        lambda argv, env: calls.append((list(argv), dict(env))) or 7,
    )

    assert core._default_exec("python", ["python", "-V"], {"A": "1"}) == 7
    assert calls == [(["python", "-V"], {"A": "1"})]


def test_run_command_redacts_credentials(tmp_path: Path) -> None:
    script = (
        "import sys; "
        "print('https://user:pass@example.com token=abc', file=sys.stderr); "
        'print(\'{"api_key": "secret-value"}\', file=sys.stderr); '
        "print('Authorization: Bearer abcdefghijklmnop', file=sys.stderr)"
    )
    result = core.run_command([sys.executable, "-c", script], tmp_path, {}, 5)

    assert "user:pass" not in result["stderr"]
    assert "token=abc" not in result["stderr"]
    assert "secret-value" not in result["stderr"]
    assert "abcdefghijklmnop" not in result["stderr"]
    assert "https://***@example.com token=***" in result["stderr"]
    assert '"api_key": ***' in result["stderr"]
    assert "Bearer ***" in result["stderr"]


def test_steps_redact_credentials_in_commands(tmp_path: Path) -> None:
    """A token in an install argument must never reach the reported steps."""

    spec = _spec(install_args=("--index-url=https://user:s3cret@example/simple", "example-mcp"))
    runner = ScriptedRunner([0, 0, 1])

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    serialized = json.dumps(result["steps"])
    assert "s3cret" not in serialized
    assert "user:s3cret" not in serialized
    assert "***" in serialized


def test_run_command_rejects_an_empty_command(tmp_path: Path) -> None:
    result = core.run_command([], tmp_path, {}, 1)
    assert result["returncode"] == 2
    assert result["stderr"] == "empty command"


def test_entrypoint_with_spaces_is_passed_as_one_argument(tmp_path: Path) -> None:
    spec = _spec(entrypoint="first run.py")
    python = _fake_venv(tmp_path, spec)
    execs = ExecRecorder()

    code = bootstrap(
        [],
        tmp_path,
        spec,
        exec_fn=execs,
        run=RunRecorder(),
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    assert code == 0
    assert execs.calls[0][1] == [str(python), str(tmp_path / "first run.py")]


def test_good_running_python_without_continuation_hands_off_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first pass may exec once, to record the handoff in ``env_var``."""

    monkeypatch.delenv("EXAMPLE_MCP_INTERPRETER", raising=False)
    execs = ExecRecorder()
    code = bootstrap(
        [],
        tmp_path,
        _spec(),
        exec_fn=execs,
        run=RunRecorder(),
        current=(3, 14, 10),
    )

    assert code == 0
    assert len(execs.calls) == 1
    assert execs.calls[0][0] == sys.executable


def test_handed_off_entrypoint_without_continuation_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-entry with no continuation is an error, never another exec."""

    monkeypatch.setenv("EXAMPLE_MCP_INTERPRETER", sys.executable)
    execs = ExecRecorder()

    code = bootstrap([], tmp_path, _spec(), exec_fn=execs, run=RunRecorder(), current=(3, 15, 2))

    report = json.loads(capsys.readouterr().out)
    assert code == 7
    assert report["reason"] == "missing_continuation"
    assert report["handed_off"] is True
    assert execs.calls == []


def test_a_stale_env_var_that_names_nothing_still_hands_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover value that is not an interpreter must not fail the first pass."""

    monkeypatch.setenv("EXAMPLE_MCP_INTERPRETER", str(tmp_path / "gone" / "python"))
    execs = ExecRecorder()

    code = bootstrap([], tmp_path, _spec(), exec_fn=execs, run=RunRecorder(), current=(3, 15, 2))

    assert code == 0
    assert len(execs.calls) == 1


def _write_probe(tmp_path: Path, body: str) -> tuple[Path, Path]:
    counter = tmp_path / "count"
    script = tmp_path / "entry.py"
    script.write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "from python_mcp_bootstrap import BootstrapSpec, bootstrap\n"
        f"counter = Path({str(counter)!r})\n"
        "n = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(n + 1))\n" + body,
        encoding="utf-8",
    )
    return script, counter


def _run_probe(script: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run a probe with no inherited handoff, so test order cannot matter."""

    root = Path(__file__).resolve().parents[1]
    clean = {
        key: value
        for key, value in os.environ.items()
        if key not in {"MCP_BOOTSTRAP_INTERPRETER", "EXAMPLE_MCP_INTERPRETER"}
    }
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        env={**clean, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_an_entrypoint_without_a_continuation_is_bounded(tmp_path: Path) -> None:
    """Regression: this path used to re-exec the entry point in a tight loop.

    An earlier revision of this path reached 122 re-entries in about five
    seconds.  A naive entry point now starts twice at most: once to record the
    handoff, once to report that it has nowhere to continue.
    """

    script, counter = _write_probe(
        tmp_path,
        "spec = BootstrapSpec(app='probe', entrypoint='entry.py')\n"
        "raise SystemExit(\n"
        "    bootstrap([], Path(__file__).resolve().parent, spec, current=(3, 15, 2))\n"
        ")\n",
    )

    done = _run_probe(script, tmp_path)

    assert done.returncode == 7
    assert counter.read_text(encoding="utf-8") == "2"
    assert json.loads(done.stdout)["reason"] == "missing_continuation"


def test_an_entrypoint_that_branches_on_env_var_continues(tmp_path: Path) -> None:
    """The handoff signal must stay usable.

    This is the supported shape: branch on ``env_var``, and only call
    ``bootstrap()`` when it is unset.  Breaking it turns a working wrapper into
    a ``missing_continuation`` failure.
    """

    script, counter = _write_probe(
        tmp_path,
        "if os.environ.get('MCP_BOOTSTRAP_INTERPRETER'):\n"
        "    print('CONTINUED')\n"
        "    raise SystemExit(0)\n"
        "spec = BootstrapSpec(app='probe', entrypoint='entry.py')\n"
        "raise SystemExit(\n"
        "    bootstrap([], Path(__file__).resolve().parent, spec, current=(3, 15, 2))\n"
        ")\n",
    )

    done = _run_probe(script, tmp_path)

    assert done.returncode == 0
    assert "CONTINUED" in done.stdout
    assert counter.read_text(encoding="utf-8") == "2"


def test_provision_without_verify_import_succeeds(tmp_path: Path) -> None:
    spec = _spec(verify_import=None)
    runner = RunRecorder()

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is True
    assert not any("import_module" in command for command in runner.commands)


def test_post_install_probe_failure_is_reported(tmp_path: Path) -> None:
    result = provision(
        tmp_path,
        _spec(),
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 13, 0),
    )

    assert result["ok"] is False
    assert result["reason"] == "provision_failed"
    assert result["python_version"] is None


def test_move_aside_uses_a_numbered_backup(tmp_path: Path) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)
    (tmp_path / ".venv.previous").mkdir()
    probes: list[str] = []

    def probe(_exe: str) -> tuple[int, int, int]:
        probes.append(_exe)
        return (3, 9, 6) if len(probes) == 1 else (3, 15, 2)

    result = provision(tmp_path, spec, uv="/fake/uv", run=RunRecorder(), probe=probe)

    assert result["ok"] is True
    assert (tmp_path / ".venv.previous-1").is_dir()


def test_venv_directory_locked_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".venv").mkdir()

    def locked(_path: Path) -> Path:
        raise OSError("locked")

    monkeypatch.setattr(core, "_move_aside", locked)
    result = provision(
        tmp_path,
        _spec(),
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    assert result["reason"] == "venv_locked"


@pytest.mark.skipif(os.name == "nt", reason="POSIX probe script")
def test_interpreter_version_rejects_a_failed_probe(tmp_path: Path) -> None:
    exe = tmp_path / "python"
    exe.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    exe.chmod(0o755)
    assert interpreter_version(exe) is None


def test_existing_good_venv_with_missing_module_needs_repair_consent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec()
    python = _fake_venv(tmp_path, spec)
    execs = ExecRecorder()

    code = bootstrap(
        [],
        tmp_path,
        spec,
        exec_fn=execs,
        run=RunRecorder(failures={"example_mcp"}),
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 6
    assert report["reason"] == "needs_install"
    assert report["app"] == "example-mcp"
    assert report["interpreter"] == str(python)
    assert report["card"] == spec.repair_card
    assert report["next"] == "python first_run.py --install-python"
    assert execs.calls == []


def test_existing_good_venv_with_missing_module_repairs_with_consent(tmp_path: Path) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)
    execs = ExecRecorder()
    runner = ScriptedRunner([1, 1, 0, 0])

    code = bootstrap(
        ["--install-python"],
        tmp_path,
        spec,
        exec_fn=execs,
        run=runner,
        uv="/fake/uv",
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    assert code == 0
    commands = runner.commands
    assert any("pip install --python" in command and "-e ." in command for command in commands)
    assert any("example_mcp" in command for command in commands)
    assert not any("python install" in command for command in commands)
    assert not any("venv .venv" in command for command in commands)
    # A reuse/repair run never installed the pin, so it must not advance the
    # project pin to an interpreter that was not downloaded.
    assert (tmp_path / ".python-version").exists() is False


def test_flat_layout_verify_import_fails_without_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A flat package at the project root must not satisfy the check.

    The project's flat layout puts ``example_mcp`` on ``sys.path`` through the
    cwd, which is exactly what the unisolated verify command trusted.  The
    real verify runner is used here, with the current interpreter standing in
    for the floor-meeting ``.venv``, so cwd leaking back in fails the test.
    """

    flat = tmp_path / "example_mcp"
    flat.mkdir()
    (flat / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    spec = _spec()
    execs = ExecRecorder()
    monkeypatch.setattr(
        core,
        "venv_python",
        lambda _root, _venv_dir=core.VENV_DIR: Path(sys.executable),
    )

    # Premise: the module imports through the cwd when the path is not isolated.
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONSAFEPATH", "PYTHONHOME"}
    }
    plain = core.run_command([sys.executable, "-c", "import example_mcp"], tmp_path, clean_env, 60)
    assert plain["returncode"] == 0

    code = bootstrap(
        [],
        tmp_path,
        spec,
        exec_fn=execs,
        current=(3, 12, 13),
        probe=lambda _exe: (3, 15, 2),
    )

    out = capsys.readouterr().out
    assert code == 6
    report = json.loads(out)
    assert report["reason"] == "needs_install"
    assert report["installed"] is False
    assert execs.calls == []


def test_reuse_path_does_not_write_pin_ahead_of_installed_interpreter(tmp_path: Path) -> None:
    """Repairing an existing venv must not write the un-installed pin."""

    spec = _spec()
    _fake_venv(tmp_path, spec)
    pin = tmp_path / ".python-version"
    pin.write_text("3.14.10\n", encoding="utf-8")
    runner = ScriptedRunner([1, 0, 0])

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 14, 10),
    )

    assert result["ok"] is True
    assert result["ran_install"] is True
    assert result["python_version"] == "3.14.10"
    assert not any("python install" in command for command in runner.commands)
    assert pin.read_text(encoding="utf-8") == "3.14.10\n"


def test_reuse_path_leaves_an_absent_pin_absent(tmp_path: Path) -> None:
    spec = _spec()
    _fake_venv(tmp_path, spec)
    runner = ScriptedRunner([1, 0, 0])

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=runner,
        probe=lambda _exe: (3, 14, 10),
    )

    assert result["ok"] is True
    assert not any("python install" in command for command in runner.commands)
    assert (tmp_path / ".python-version").exists() is False


def test_utf16_pin_file_returns_pin_write_failed(tmp_path: Path) -> None:
    """A non-UTF-8 pin file is a JSON failure, not an uncaught crash."""

    spec = _spec()
    (tmp_path / ".python-version").write_bytes("3.15.2\n".encode("utf-16"))

    result = provision(
        tmp_path,
        spec,
        uv="/fake/uv",
        run=RunRecorder(),
        probe=lambda _exe: (3, 15, 2),
    )

    assert result["ok"] is False
    assert result["reason"] == "pin_write_failed"
    assert result["detail"]
