"""Release invariant tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import release_check
from scripts.release_check import (
    ROOT,
    _checksum_errors,
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
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert package_version(ROOT) == project["project"]["version"]


def test_current_tree_is_release_ready() -> None:
    assert check(ROOT, allow_dirty=True) == []


@pytest.mark.skipif(
    not _local_tag_is_annotated(f"v{package_version(ROOT)}"),
    reason="release tag is absent or not annotated; CI restores it after checkout",
)
def test_matching_release_tag_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_check, "_release_asset_errors", lambda *_args: [])
    assert check(ROOT, allow_dirty=True, tag=f"v{package_version(ROOT)}") == []


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


FAKE_GH = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as handle:
    state = json.load(handle)
args = sys.argv[1:]
if len(args) >= 2 and args[0] == "api" and "releases?per_page=100" in args[1]:
    if state.get("unreadable"):
        sys.exit(1)
    print(json.dumps(state["releases"]))
    sys.exit(0)
if len(args) >= 2 and args[0] == "api" and "/releases/assets/" in args[1]:
    asset_id = args[1].rsplit("/", 1)[1]
    data = state["contents"].get(asset_id)
    if data is None:
        sys.exit(1)
    sys.stdout.buffer.write(data.encode("utf-8"))
    sys.exit(0)
sys.exit(2)
"""


def _install_fake_gh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    releases: list[dict[str, object]],
    contents: dict[str, str],
    unreadable: bool = False,
) -> None:
    if os.name == "nt":
        implementation = tmp_path / "gh_impl.py"
        implementation.write_text(FAKE_GH, encoding="utf-8")
        script = tmp_path / "gh.cmd"
        script.write_text(
            f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n',
            encoding="utf-8",
        )
    else:
        script = tmp_path / "gh"
        script.write_text(FAKE_GH, encoding="utf-8")
        script.chmod(0o755)
    state = tmp_path / "gh-state.json"
    state.write_text(
        json.dumps({"releases": releases, "contents": contents, "unreadable": unreadable}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    # An extracted sdist has no git remote; pin the slug so these tests are
    # independent of the checkout.
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: str(script))


def _release_fixture(
    version: str = "0.1.0",
    *,
    draft: bool = False,
    tamper: bool = False,
    drop: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    wheel = f"python_mcp_bootstrap-{version}-py3-none-any.whl"
    sdist = f"python_mcp_bootstrap-{version}.tar.gz"
    payloads = {
        wheel: "wheel-bytes",
        sdist: "sdist-bytes",
        f"{wheel}.sigstore.json": "wheel-signature",
        f"{sdist}.sigstore.json": "sdist-signature",
        "SHA256SUMS.sigstore.json": "sums-signature",
        "provenance.intoto.jsonl": "provenance-bytes",
    }
    sums = "\n".join(
        f"{hashlib.sha256(payloads[name].encode()).hexdigest()}  {name}" for name in (wheel, sdist)
    )
    payloads["SHA256SUMS"] = sums + "\n"
    order = [
        wheel,
        sdist,
        "SHA256SUMS",
        f"{wheel}.sigstore.json",
        f"{sdist}.sigstore.json",
        "SHA256SUMS.sigstore.json",
        "provenance.intoto.jsonl",
    ]
    contents: dict[str, str] = {}
    assets: list[dict[str, object]] = []
    for index, name in enumerate(order, start=1):
        if name == drop:
            continue
        payload = "tampered" if tamper and name == wheel else payloads[name]
        contents[str(index)] = payload
        assets.append({"name": name, "id": index})
    return [{"tag_name": f"v{version}", "draft": draft, "assets": assets}], contents


def test_release_asset_check_skips_without_gh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: None)
    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" in capsys.readouterr().err


def test_published_release_verifies_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    releases, contents = _release_fixture()
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" not in capsys.readouterr().err


def test_draft_release_verifies_assets_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    releases, contents = _release_fixture(draft=True)
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" not in capsys.readouterr().err


def test_unreadable_release_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_gh(monkeypatch, tmp_path, releases=[], contents={}, unreadable=True)
    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" in capsys.readouterr().err


def test_missing_release_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_gh(monkeypatch, tmp_path, releases=[], contents={})
    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "skipping" in capsys.readouterr().err


def test_missing_asset_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wheel = "python_mcp_bootstrap-0.1.0-py3-none-any.whl"
    releases, contents = _release_fixture(drop=wheel)
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    errors = _release_asset_errors(ROOT, "v0.1.0", "0.1.0")
    assert any("missing asset" in error and wheel in error for error in errors)


def test_checksum_mismatch_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    releases, contents = _release_fixture(tamper=True)
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    errors = _release_asset_errors(ROOT, "v0.1.0", "0.1.0")
    assert any("digest mismatch" in error for error in errors)


def test_asset_download_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    releases, contents = _release_fixture()
    wheel_id = next(
        str(asset["id"]) for asset in releases[0]["assets"] if str(asset["name"]).endswith(".whl")
    )
    del contents[wheel_id]
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    errors = _release_asset_errors(ROOT, "v0.1.0", "0.1.0")
    assert any("could not be downloaded" in error for error in errors)


def test_repo_slug_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    assert release_check._repo_slug(ROOT) == "owner/repo"


def test_repo_slug_falls_back_to_the_git_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(
        release_check,
        "_git",
        lambda *_args: SimpleNamespace(
            returncode=0, stdout="git@github.com:owner/repo.git\n", stderr=""
        ),
    )
    assert release_check._repo_slug(ROOT) == "owner/repo"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "owner/repo"),
        ("https://example.com/owner/repo", None),
    ],
)
def test_slug_from_remote(url: str, expected: str | None) -> None:
    assert release_check._slug_from_remote(url) == expected


def test_changelog_duplicate_heading_is_reported() -> None:
    text = "# Changelog\n\n## 0.1.0 — 2026-11-04\n\nfirst\n\n## 0.1.0 — 2026-11-05\n\nsecond\n"
    assert release_check._duplicate_heading_errors(text) == [
        "CHANGELOG has duplicate entries for 0.1.0"
    ]


def test_real_changelog_has_no_duplicate_headings() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_check._duplicate_heading_errors(text) == []


def test_checksum_errors_accept_matching_files(tmp_path: Path) -> None:
    wheel = tmp_path / "python_mcp_bootstrap-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "python_mcp_bootstrap-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    lines = []
    for artifact in (wheel, sdist):
        digest = release_check._sha256(artifact)
        lines.append(f"{digest}  ./{artifact.name}")
    (tmp_path / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert _checksum_errors(tmp_path, "0.1.0") == []


def test_checksum_errors_detect_mismatch_and_missing(tmp_path: Path) -> None:
    wheel = tmp_path / "python_mcp_bootstrap-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"tampered")
    (tmp_path / "SHA256SUMS").write_text(f"{'0' * 64}  {wheel.name}\n", encoding="utf-8")

    errors = _checksum_errors(tmp_path, "0.1.0")
    assert any("digest mismatch" in error for error in errors)
    assert any("tar.gz" in error for error in errors)


def test_check_requires_a_notes_file(tmp_path: Path) -> None:
    failures = check(tmp_path, allow_dirty=True)
    assert any("pyproject.toml" in failure for failure in failures)
