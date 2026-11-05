"""CLI tests for the read-only diagnostic."""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from python_mcp_bootstrap import __version__
from python_mcp_bootstrap.cli import main


def test_check_reports_the_pin(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["version"] == __version__
    assert payload["required"] == ">=3.12.0"
    assert payload["pin"] == "3.15.2"
    assert "uv" in payload


def test_no_arguments_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().out


def test_version_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entrypoint_runs_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["python_mcp_bootstrap", "--check"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("python_mcp_bootstrap", run_name="__main__")
    assert raised.value.code == 0
    assert '"ok": true' in capsys.readouterr().out
