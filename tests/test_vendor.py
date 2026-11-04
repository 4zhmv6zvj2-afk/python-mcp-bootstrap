"""Vendor tooling tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.vendor import MANIFEST_NAME, main, package_version, sha256, vendor

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


def test_package_version_requires_a_version_literal(tmp_path: Path) -> None:
    init = tmp_path / "src" / "python_mcp_bootstrap" / "__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no __version__"):
        package_version(tmp_path)


def test_check_detects_a_missing_vendored_file(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    dest = tmp_path / _dest()
    dest.unlink()

    checked = vendor(tmp_path, _dest(), check=True)
    assert checked["ok"] is False
    assert any("missing vendored file" in error for error in checked["errors"])


def test_check_detects_a_missing_manifest(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    (tmp_path / _dest()).with_name(MANIFEST_NAME).unlink()

    checked = vendor(tmp_path, _dest(), check=True)
    assert checked["ok"] is False
    assert any("missing manifest" in error for error in checked["errors"])


def test_check_detects_an_unreadable_manifest(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    manifest_path = (tmp_path / _dest()).with_name(MANIFEST_NAME)
    manifest_path.write_text("not json", encoding="utf-8")

    checked = vendor(tmp_path, _dest(), check=True)
    assert checked["ok"] is False
    assert any("unreadable manifest" in error for error in checked["errors"])


def test_check_detects_a_non_object_manifest(tmp_path: Path) -> None:
    vendor(tmp_path, _dest())
    manifest_path = (tmp_path / _dest()).with_name(MANIFEST_NAME)
    manifest_path.write_text("[]", encoding="utf-8")

    checked = vendor(tmp_path, _dest(), check=True)
    assert checked["ok"] is False
    assert "manifest is not a JSON object" in checked["errors"]


def test_vendor_rejects_an_absolute_dest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside target"):
        vendor(tmp_path, str(tmp_path / "x.py"))


def test_vendor_rejects_the_manifest_as_dest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="manifest"):
        vendor(tmp_path, MANIFEST_NAME)


def test_vendor_rejects_a_file_as_target(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        vendor(target, _dest())


def test_cli_reports_errors_and_check_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--target", str(tmp_path), "--dest", "../outside.py"]) == 2
    assert "vendor:" in capsys.readouterr().err

    vendor(tmp_path, _dest())
    target = tmp_path / _dest()
    target.write_text(target.read_text(encoding="utf-8") + "\n# edit\n", encoding="utf-8")
    assert main(["--target", str(tmp_path), "--dest", _dest(), "--check"]) == 1
    assert "vendor:" in capsys.readouterr().err


def test_cli_prints_success_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--target", str(tmp_path), "--dest", _dest()]) == 0
    assert "vendored:" in capsys.readouterr().out
    assert main(["--target", str(tmp_path), "--dest", _dest(), "--check"]) == 0
    assert "verified:" in capsys.readouterr().out
