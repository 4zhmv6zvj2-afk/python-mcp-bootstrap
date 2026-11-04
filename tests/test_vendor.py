"""Vendor tooling tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.vendor import MANIFEST_NAME, main, sha256, vendor

from python_mcp_bootstrap import __version__


def _dest() -> str:
    return "src/example/_vendor/python_mcp_bootstrap.py"


def test_vendor_writes_core_and_manifest(tmp_path: Path) -> None:
    result = vendor(tmp_path, _dest())

    assert result["ok"] is True
    dest = tmp_path / _dest()
    manifest_path = dest.with_name(MANIFEST_NAME)
    assert dest.is_file()
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "python-mcp-bootstrap"
    assert manifest["version"] == __version__
    assert manifest["file"] == dest.name
    assert manifest["sha256"] == sha256(dest)
    assert manifest["tag"] == f"v{__version__}"
    assert manifest["source"].startswith("https://github.com/")
    commit = manifest["commit"]
    if (Path(__file__).resolve().parents[1] / ".git").exists():
        assert len(commit) == 40
        assert all(character in "0123456789abcdef" for character in commit)
    else:
        # An unpacked source archive has no git metadata to record.
        assert commit == "unknown"


def test_vendor_check_passes_then_detects_an_edit(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    assert vendor(tmp_path, _dest(), check=True)["ok"] is True

    dest = tmp_path / _dest()
    dest.write_text(dest.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    result = vendor(tmp_path, _dest(), check=True)

    assert result["ok"] is False
    assert any("differs" in error for error in result["errors"])


def test_vendor_check_detects_manifest_drift(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    manifest_path = (tmp_path / _dest()).with_name(MANIFEST_NAME)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = vendor(tmp_path, _dest(), check=True)

    assert result["ok"] is False
    assert any("version" in error for error in result["errors"])


def test_vendor_rejects_a_path_outside_the_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside"):
        vendor(tmp_path, "../outside.py")
    with pytest.raises(ValueError, match="inside"):
        vendor(tmp_path, str(tmp_path / "absolute.py"))


def test_vendor_is_idempotent(tmp_path: Path) -> None:
    first = vendor(tmp_path, _dest())
    second = vendor(tmp_path, _dest())

    assert first["changed"] is True
    assert second["changed"] is False


def test_vendor_cli_reports_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--target", str(tmp_path), "--dest", _dest(), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["check"] is False
