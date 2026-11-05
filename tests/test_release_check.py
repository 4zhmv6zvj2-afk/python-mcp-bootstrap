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

from python_mcp_bootstrap import core as bootstrap_core


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


def test_version_is_dynamic_and_points_at_the_package_init() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert release_check._version_config_errors(data["project"], data["tool"]) == []
    assert package_version(ROOT)  # still the source of truth for tags and notes


def _version_config(project: dict[str, object], tool: dict[str, object]) -> list[str]:
    return release_check._version_config_errors(project, tool)


@pytest.mark.parametrize(
    ("project", "tool", "message"),
    [
        (
            {"dynamic": ["version"], "version": "0.1.5"},
            {"hatch": {"version": {"path": "src/python_mcp_bootstrap/__init__.py"}}},
            "static version",
        ),
        (
            {},
            {"hatch": {"version": {"path": "src/python_mcp_bootstrap/__init__.py"}}},
            "must be dynamic",
        ),
        (
            {"dynamic": ["version"]},
            {"hatch": {"version": {"path": "src/other/__init__.py"}}},
            "hatch version path",
        ),
        ({"dynamic": ["version"]}, {}, "hatch version path"),
    ],
)
def test_version_configuration_errors(
    project: dict[str, object], tool: dict[str, object], message: str
) -> None:
    errors = _version_config(project, tool)
    assert any(message in error for error in errors)


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


def _required_asset_names(version: str = "0.1.0") -> list[str]:
    wheel = f"python_mcp_bootstrap-{version}-py3-none-any.whl"
    sdist = f"python_mcp_bootstrap-{version}.tar.gz"
    return [
        wheel,
        sdist,
        "SHA256SUMS",
        f"{wheel}.sigstore.json",
        f"{sdist}.sigstore.json",
        "SHA256SUMS.sigstore.json",
        "provenance.intoto.jsonl",
    ]


@pytest.mark.parametrize("missing", _required_asset_names())
def test_every_required_asset_is_enforced(
    missing: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    releases, contents = _release_fixture(drop=missing)
    _install_fake_gh(monkeypatch, tmp_path, releases=releases, contents=contents)

    errors = _release_asset_errors(ROOT, "v0.1.0", "0.1.0")
    assert any("missing asset" in error and missing in error for error in errors)


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


def test_package_version_requires_a_version_literal(tmp_path: Path) -> None:
    init = tmp_path / "src" / "python_mcp_bootstrap" / "__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no __version__"):
        package_version(tmp_path)


def test_tracked_text_skips_unreadable_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release_check,
        "_git",
        lambda *_args: SimpleNamespace(returncode=0, stdout="missing.txt\n", stderr=""),
    )
    assert release_check._tracked_text(ROOT) == {}


def test_repo_slug_returns_none_without_a_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(
        release_check,
        "_git",
        lambda *_args: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert release_check._repo_slug(ROOT) is None


@pytest.mark.parametrize(
    "raw",
    ["", "  \n\t ", '{"not": "a list"}', '[{"tag_name": "v1"}]'],
)
def test_parse_release_pages_ignores_non_list_pages(raw: str) -> None:
    pages = release_check._parse_release_pages(raw)
    assert all(isinstance(page, dict) for page in pages)


def test_release_assets_handles_a_missing_assets_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_gh(
        monkeypatch,
        tmp_path,
        releases=[{"tag_name": "v0.1.0"}],
        contents={},
    )
    g = release_check.shutil.which("gh")
    assert g is not None
    assert release_check._release_assets(ROOT, g, "v0.1.0", "owner/repo") == {}


def test_release_asset_check_skips_without_a_repo_slug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release_check.shutil, "which", lambda _name: "/fake/gh")
    monkeypatch.setattr(release_check, "_repo_slug", lambda _root: None)
    assert _release_asset_errors(ROOT, "v0.1.0", "0.1.0") == []
    assert "cannot determine the repository" in capsys.readouterr().err


def test_checksum_errors_report_malformed_and_missing_entries(tmp_path: Path) -> None:
    wheel = tmp_path / "python_mcp_bootstrap-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    (tmp_path / "SHA256SUMS").write_text(
        "not-a-valid-line\n" + f"{'0' * 64}  absent.bin\n" + f"{'1' * 64}  {wheel.name}\n",
        encoding="utf-8",
    )
    errors = _checksum_errors(tmp_path, "0.1.0")
    assert any("malformed SHA256SUMS" in error for error in errors)
    assert any("missing asset absent.bin" in error for error in errors)
    assert any("does not list" in error and "tar.gz" in error for error in errors)


def test_check_reports_unreadable_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [toml", encoding="utf-8")
    failures = check(tmp_path, allow_dirty=True)
    assert any("unreadable pyproject.toml" in failure for failure in failures)


def test_check_reports_a_non_git_tree(tmp_path: Path) -> None:
    failures = check(tmp_path, allow_dirty=False)
    assert any("not a Git checkout" in failure for failure in failures)


def test_check_reports_machine_specific_tracked_text(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    pattern = "/Vol" + "umes/" + "SSD " + "storage/project"
    (tmp_path / "notes.txt").write_text(f"built in {pattern}\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "release_check.py").write_text("/Vol" + "umes/ignored-here\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "notes.txt", "scripts/release_check.py"],
        check=True,
    )
    failures = check(tmp_path, allow_dirty=True)
    flagged = [failure for failure in failures if "machine-specific" in failure]
    assert any("notes.txt" in failure for failure in flagged)
    assert not any("scripts/release_check.py" in failure for failure in flagged)


def test_main_reports_failures_and_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(release_check, "check", lambda **_kwargs: ["boom"])
    assert release_check.main(["--allow-dirty"]) == 1
    assert "release check failed: boom" in capsys.readouterr().err

    monkeypatch.setattr(release_check, "check", lambda **_kwargs: [])
    assert release_check.main(["--allow-dirty"]) == 0
    assert "release check: ok" in capsys.readouterr().out


def test_core_constants_are_read_from_the_source() -> None:
    constants = release_check._core_constants(ROOT / "src" / "python_mcp_bootstrap" / "core.py")
    assert constants == (bootstrap_core.PIN, bootstrap_core.REQUIRED)


def test_core_constants_missing_is_reported(tmp_path: Path) -> None:
    core_path = tmp_path / "core.py"
    core_path.write_text("PIN = 1\n", encoding="utf-8")
    assert release_check._core_constants(core_path) is None


def _release_tree(root: Path) -> None:
    package = root / "src" / "python_mcp_bootstrap"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (package / "core.py").write_text(
        'PIN = "3.15.2"\nREQUIRED: Version = (3, 12, 0)\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "python-mcp-bootstrap"\n'
        'dynamic = ["version"]\n'
        'requires-python = ">=3.12"\n'
        'license = "MIT"\n'
        "\n[tool.hatch.version]\n"
        'path = "src/python_mcp_bootstrap/__init__.py"\n',
        encoding="utf-8",
    )
    (root / ".python-version").write_text("3.15\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0 — 2026-01-01\n", encoding="utf-8")
    notes = root / "docs" / "releases"
    notes.mkdir(parents=True)
    (notes / "0.1.0.md").write_text("notes\n", encoding="utf-8")
    (root / "docs" / "integration.md").write_text("", encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "vendor.py").write_text("", encoding="utf-8")


def test_check_fails_when_pin_file_disagrees_with_core(tmp_path: Path) -> None:
    _release_tree(tmp_path)
    (tmp_path / ".python-version").write_text("9.9.9\n", encoding="utf-8")

    failures = check(tmp_path, allow_dirty=True)
    assert any("python pin line is not 3.15" in failure for failure in failures)


def test_check_reports_unreadable_core_constants(tmp_path: Path) -> None:
    _release_tree(tmp_path)
    (tmp_path / "src" / "python_mcp_bootstrap" / "core.py").write_text(
        "undefined = True\n", encoding="utf-8"
    )

    failures = check(tmp_path, allow_dirty=True)
    assert any("cannot read PIN and REQUIRED" in failure for failure in failures)
