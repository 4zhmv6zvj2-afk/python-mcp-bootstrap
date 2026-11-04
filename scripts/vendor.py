#!/usr/bin/env python3
"""Vendor the bootstrap core into a consumer tree.

The vendored file is copied byte-for-byte and accompanied by a ``VENDOR.json``
manifest.  ``--check`` verifies an existing copy without writing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "python_mcp_bootstrap" / "core.py"
NAME = "python-mcp-bootstrap"
SOURCE = "https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap"
MANIFEST_NAME = "VENDOR.json"


def package_version(root: Path = ROOT) -> str:
    """Read the package version without importing the package."""

    init = root / "src" / "python_mcp_bootstrap" / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ = "):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"no __version__ in {init}")


def git_commit(root: Path = ROOT) -> str:
    """Return the current commit, or ``unknown`` outside a Git checkout."""

    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _manifest(
    version: str, tag: str, commit: str, source: str, file_name: str, digest: str
) -> dict[str, str]:
    return {
        "name": NAME,
        "version": version,
        "tag": tag,
        "commit": commit,
        "source": source,
        "file": file_name,
        "sha256": digest,
    }


def _check_existing(
    dest_path: Path,
    manifest_path: Path,
    expected: dict[str, str],
    source_digest: str,
) -> list[str]:
    errors: list[str] = []
    if not dest_path.is_file():
        errors.append(f"missing vendored file: {dest_path}")
    if not manifest_path.is_file():
        errors.append(f"missing manifest: {manifest_path}")
    if errors:
        return errors

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]

    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"manifest {key} is {manifest.get(key)!r}, expected {value!r}")

    actual_digest = sha256(dest_path)
    if actual_digest != source_digest:
        errors.append("vendored file differs from the source core")
    if manifest.get("sha256") != actual_digest:
        errors.append("manifest sha256 does not match the vendored file")
    return errors


def vendor(
    target: Path,
    dest: str,
    *,
    tag: str | None = None,
    source: str = SOURCE,
    check: bool = False,
) -> dict[str, Any]:
    """Copy the core to ``target/dest`` and write ``VENDOR.json``.

    With ``check=True``, verify the existing copy and manifest instead of
    writing.  Paths that escape ``target`` are rejected.
    """

    target = Path(target).resolve()
    if not dest.strip():
        raise ValueError("dest must not be empty")
    if Path(dest).is_absolute():
        raise ValueError("dest must stay inside target")
    dest_path = (target / dest).resolve()
    try:
        dest_path.relative_to(target)
    except ValueError as exc:
        raise ValueError("dest must stay inside target") from exc
    if dest_path.name == MANIFEST_NAME:
        raise ValueError("dest must not be the manifest file")

    version = package_version()
    tag = tag or f"v{version}"
    commit = git_commit()
    source_digest = sha256(CORE)
    expected = _manifest(version, tag, commit, source, dest_path.name, source_digest)
    manifest_path = dest_path.with_name(MANIFEST_NAME)

    if check:
        errors = _check_existing(dest_path, manifest_path, expected, source_digest)
        return {
            "ok": not errors,
            "check": True,
            "path": str(dest_path),
            "manifest": str(manifest_path),
            "errors": errors,
        }

    if target.exists() and not target.is_dir():
        raise NotADirectoryError(str(target))
    target.mkdir(parents=True, exist_ok=True)
    changed = not dest_path.is_file() or dest_path.read_bytes() != CORE.read_bytes()
    _atomic_write(dest_path, CORE.read_bytes())
    _atomic_write(
        manifest_path,
        (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {
        "ok": True,
        "check": False,
        "path": str(dest_path),
        "manifest": str(manifest_path),
        "changed": changed,
        "data": expected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True, help="consumer checkout")
    parser.add_argument("--dest", required=True, help="path relative to target")
    parser.add_argument("--tag", help="release tag (default: v<version>)")
    parser.add_argument("--source", default=SOURCE, help="source repository URL")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the existing copy and manifest instead of writing",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    try:
        result = vendor(
            args.target,
            args.dest,
            tag=args.tag,
            source=args.source,
            check=args.check,
        )
    except (OSError, ValueError) as exc:
        print(f"vendor: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"{'verified' if result['check'] else 'vendored'}: {result['path']}")
    else:
        for error in result["errors"]:
            print(f"vendor: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
