#!/usr/bin/env python3
"""Check release invariants before tagging or publishing.

The check is offline and read-only.  It verifies metadata, the changelog,
release notes, Python compatibility, tag/version and annotated-tag agreement
when ``--tag`` is given, GitHub release assets when ``gh`` is available, and
tracked-file hygiene.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "3.15.2"
REQUIRED = ">=3.14"
LOCAL_PATTERNS = ("/Volumes/", "ssd storage", "gho_", "github_pat_")


def package_version(root: Path = ROOT) -> str:
    init = root / "src" / "python_mcp_bootstrap" / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ = "):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"no __version__ in {init}")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _tracked_text(root: Path) -> dict[str, str]:
    listed = _git(root, "ls-files")
    if listed.returncode != 0:
        return {}
    files: dict[str, str] = {}
    for name in listed.stdout.splitlines():
        path = root / name
        try:
            files[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return files


def _tag_problem(root: Path, tag: str) -> str | None:
    """Fail a lightweight tag; skip the check when the tag is not fetched."""

    result = _git(root, "cat-file", "-t", f"refs/tags/{tag}")
    if result.returncode != 0:
        print(
            f"release check: tag {tag!r} is not present; skipping annotated-tag check",
            file=sys.stderr,
        )
        return None
    if result.stdout.strip() != "tag":
        return f"tag {tag!r} is not annotated"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_names(root: Path, gh: str, tag: str) -> set[str] | None:
    """Return the published asset names, or None when the release is not readable."""

    result = subprocess.run(
        [gh, "release", "view", tag, "--json", "assets", "--jq", ".assets[].name"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"release check: release {tag!r} is not readable; skipping asset check", file=sys.stderr
        )
        return None
    return set(result.stdout.split())


def _download_assets(root: Path, gh: str, tag: str, dest: Path) -> str | None:
    """Download the checksummed artifacts; retry briefly for asset propagation."""

    for attempt in range(4):
        result = subprocess.run(
            [
                gh,
                "release",
                "download",
                tag,
                "--pattern",
                "SHA256SUMS",
                "--pattern",
                "*.whl",
                "--pattern",
                "*.tar.gz",
                "--dir",
                str(dest),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return None
        if attempt < 3:
            time.sleep(3)
    return f"release {tag!r} assets could not be downloaded"


def _checksum_errors(dest: Path, version: str) -> list[str]:
    """Verify SHA256SUMS names every artifact and matches its bytes."""

    errors: list[str] = []
    wheel = f"python_mcp_bootstrap-{version}-py3-none-any.whl"
    sdist = f"python_mcp_bootstrap-{version}.tar.gz"
    sums = dest / "SHA256SUMS"
    if not sums.is_file():
        return ["release asset check: SHA256SUMS was not downloaded"]
    listed: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            errors.append(f"release asset check: malformed SHA256SUMS line {line!r}")
            continue
        digest, name = parts
        listed.add(name)
        artifact = dest / name
        if not artifact.is_file():
            errors.append(f"release asset check: SHA256SUMS names missing asset {name}")
        elif _sha256(artifact) != digest:
            errors.append(f"release asset check: digest mismatch for {name}")
    for name in (wheel, sdist):
        if name not in listed:
            errors.append(f"release asset check: SHA256SUMS does not list {name}")
    return errors


def _release_asset_errors(root: Path, tag: str, version: str) -> list[str]:
    """Check the GitHub release assets when gh is available.

    A tag build may run before the release is created; that is reported as a
    skip, not a failure.  A readable release with missing assets, mismatched
    digests, or without signatures/provenance fails.
    """

    gh = shutil.which("gh")
    if gh is None:
        print("release check: gh not found; skipping GitHub release asset check", file=sys.stderr)
        return []
    names = _asset_names(root, gh, tag)
    if names is None:
        return []
    wheel = f"python_mcp_bootstrap-{version}-py3-none-any.whl"
    sdist = f"python_mcp_bootstrap-{version}.tar.gz"
    required = {
        wheel,
        sdist,
        "SHA256SUMS",
        f"{wheel}.sigstore.json",
        f"{sdist}.sigstore.json",
        "SHA256SUMS.sigstore.json",
        "provenance.intoto.jsonl",
    }
    errors = [f"release {tag!r} is missing asset {name}" for name in sorted(required - names)]
    if errors:
        return errors
    with tempfile.TemporaryDirectory() as temp:
        download_error = _download_assets(root, gh, tag, Path(temp))
        if download_error:
            return [download_error]
        errors.extend(_checksum_errors(Path(temp), version))
    return errors


def check(root: Path = ROOT, *, allow_dirty: bool = False, tag: str | None = None) -> list[str]:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    pyproject_path = root / "pyproject.toml"
    require(pyproject_path.is_file(), "missing pyproject.toml")
    project: dict[str, object] = {}
    if pyproject_path.is_file():
        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project = data.get("project", {})  # type: ignore[assignment]
        except (OSError, tomllib.TOMLDecodeError) as exc:
            failures.append(f"unreadable pyproject.toml: {exc}")

    try:
        version = package_version(root)
    except (OSError, RuntimeError) as exc:
        failures.append(f"unreadable package version: {exc}")
        version = ""
    require(project.get("name") == "python-mcp-bootstrap", "unexpected project name")
    require(project.get("version") == version, "pyproject version does not match package")
    require(project.get("requires-python") == REQUIRED, "requires-python is not >=3.14")
    require(project.get("license") == "MIT", "project license is not MIT")
    if tag is not None:
        require(tag == f"v{version}", f"tag {tag!r} does not match version {version!r}")
        if tag == f"v{version}":
            tag_error = _tag_problem(root, tag)
            if tag_error:
                failures.append(tag_error)
            failures.extend(_release_asset_errors(root, tag, version))

    pin_path = root / ".python-version"
    require(pin_path.is_file(), "missing .python-version")
    if pin_path.is_file():
        require(pin_path.read_text(encoding="utf-8").strip() == PIN, "python pin is not 3.15.2")

    license_path = root / "LICENSE"
    require(license_path.is_file(), "missing LICENSE")
    if license_path.is_file():
        require("MIT License" in license_path.read_text(encoding="utf-8"), "LICENSE is not MIT")

    changelog = root / "CHANGELOG.md"
    require(changelog.is_file(), "missing CHANGELOG.md")
    if changelog.is_file():
        text = changelog.read_text(encoding="utf-8")
        heading = re.compile(rf"^## {re.escape(version)} — \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
        require(bool(heading.search(text)), "CHANGELOG has no dated release entry")

    notes = root / "docs" / "releases" / f"{version}.md"
    require(notes.is_file(), f"missing release notes: {notes}")

    core = root / "src" / "python_mcp_bootstrap" / "core.py"
    require(core.is_file(), "missing core.py")
    if core.is_file():
        source = core.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(core), feature_version=(3, 12))
        except SyntaxError as exc:
            failures.append(f"core.py is not Python 3.12 syntax: {exc}")
        require("import mcp" not in source and "from mcp" not in source, "core.py imports mcp")

    require((root / "scripts" / "vendor.py").is_file(), "missing scripts/vendor.py")
    require((root / "docs" / "integration.md").is_file(), "missing docs/integration.md")

    if not allow_dirty:
        status = _git(root, "status", "--porcelain")
        if status.returncode != 0:
            failures.append("not a Git checkout")
        elif status.stdout.strip():
            failures.append("working tree is dirty")

    for name, text in _tracked_text(root).items():
        if name == "scripts/release_check.py":
            continue  # the checker owns the pattern list
        lowered = text.lower()
        for pattern in LOCAL_PATTERNS:
            if pattern.lower() in lowered:
                failures.append(f"machine-specific path or secret in {name}: {pattern}")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--tag", help="release tag that must equal v<version>")
    args = parser.parse_args(argv)
    failures = check(allow_dirty=args.allow_dirty, tag=args.tag)
    if failures:
        for failure in failures:
            print(f"release check failed: {failure}", file=sys.stderr)
        return 1
    print("release check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
