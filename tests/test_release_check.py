"""Release invariant tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import release_check
from scripts.release_check import (
    ROOT,
    _release_asset_errors,
    _tag_problem,
    check,
    package_version,
)


def _local_tag_is_annotated(tag: str) -> bool:
    """Return whether ``tag`` exists locally as an annotated tag object.

    A tag-event checkout can leave a lightweight ref at the release tag, and a
    shallow clone may not have the tag at all.  Both cases are environment
    facts, not a regression in the release gate, so the matching-tag test skips
    instead of failing.  CI restores the annotated ref before this runs.
    """

    result = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-t", f"refs/tags/{tag}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "tag"


def test_package_version_matches_the_release() -> None:
    assert package_version(ROOT) == "0.1.0"


def test_current_tree_is_release_ready() -> None:
    assert check(ROOT, allow_dirty=True) == []


@pytest.mark.skipif(
    not _local_tag_is_annotated("v0.1.0"),
    reason="local v0.1.0 is absent or not annotated; CI restores it after checkout",
)
def test_matching_release_tag_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_check, "_release_asset_errors", lambda *_args: [])
    assert check(ROOT, allow_dirty=True, tag="v0.1.0") == []


def test_mismatched_release_tag_fails() -> None:
    failures = check(ROOT, allow_dirty=True, tag="v9.9.9")
    assert any("tag" in failure for failure in failures)


def test_tag_problem_requires_an_annotated_tag(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "commit.gpgsign=false", "commit", "-qm", "x"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "tag", "light"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "tag", "-a", "annotated", "-m", "annotated"], check=True
    )

    assert _tag_problem(tmp_path, "light") == "tag 'light' is not annotated"
    assert _tag_problem(tmp_path, "annotated") is None
    assert _tag_problem(tmp_path, "missing") is None


def test_release_asset_check_skips_without_gh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: None)
    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" in capsys.readouterr().err


def test_release_asset_check_reports_missing_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: "/fake/gh")
    result = SimpleNamespace(
        returncode=0,
        stdout="python_mcp_bootstrap-0.1.0-py3-none-any.whl\nSHA256SUMS\n",
        stderr="",
    )
    monkeypatch.setattr(release_check.subprocess, "run", lambda *_args, **_kwargs: result)

    errors = _release_asset_errors(ROOT, "v0.1.0", "0.1.0")
    assert any("tar.gz" in error for error in errors)


def test_release_asset_check_accepts_full_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: "/fake/gh")
    result = SimpleNamespace(
        returncode=0,
        stdout=(
            "python_mcp_bootstrap-0.1.0-py3-none-any.whl\n"
            "python_mcp_bootstrap-0.1.0.tar.gz\n"
            "SHA256SUMS\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(release_check.subprocess, "run", lambda *_args, **_kwargs: result)

    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []


def test_check_requires_a_notes_file(tmp_path: Path) -> None:
    failures = check(tmp_path, allow_dirty=True)
    assert any("pyproject.toml" in failure for failure in failures)
