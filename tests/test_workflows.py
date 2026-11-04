"""Workflow guardrails: preparing artifacts and publishing them stay separate."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from python_mcp_bootstrap import core

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(),
    reason="workflow files are not shipped in the sdist",
)


def _load(name: str) -> dict[str, Any]:
    yaml = YAML(typ="base")  # every scalar is a string, so ``on:`` stays "on"
    data = yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(document: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return document["jobs"][job]["steps"]


def _runs(document: dict[str, Any], job: str) -> list[str]:
    return [str(step["run"]) for step in _steps(document, job) if "run" in step]


def test_publish_workflow_cannot_modify_release_assets() -> None:
    document = _load("publish.yml")
    job = document["jobs"]["publish"]

    assert document.get("permissions", {}).get("contents", "read") == "read"
    assert job.get("permissions", {}).get("contents", "read") == "read"
    assert job.get("environment") == "pypi"
    steps = _steps(document, "publish")
    assert all("gh release upload" not in str(step.get("run", "")) for step in steps)
    pypa = [
        index
        for index, step in enumerate(steps)
        if "gh-action-pypi-publish" in str(step.get("uses", ""))
    ]
    assert len(pypa) == 1
    assert steps[pypa[0]]["with"]["packages-dir"] == "pypi-dist/"
    assert any(
        "python scripts/release_check.py" in str(step.get("run", "")) for step in steps[: pypa[0]]
    )


def test_prepare_release_attaches_assets_only_to_a_draft() -> None:
    document = _load("prepare-release.yml")
    job = document["jobs"]["prepare"]

    assert "gh-action-pypi-publish" not in " ".join(
        str(step.get("uses", "")) for step in _steps(document, "prepare")
    )
    assert "environment" not in job
    assert job["permissions"]["contents"] == "write"
    runs = _runs(document, "prepare")
    assert any("gh release create" in run and "--draft" in run for run in runs)
    assert any("gh release upload" in run for run in runs)


def test_publish_requires_a_published_immutable_release() -> None:
    document = _load("publish.yml")
    guard = next(
        run for run in _runs(document, "publish") if ".draft" in run and ".immutable" in run
    )

    assert "still a draft" in guard
    assert "not immutable" in guard


def test_prepare_release_detects_existing_drafts() -> None:
    document = _load("prepare-release.yml")
    runs = _runs(document, "prepare")
    create = next(run for run in runs if "gh release create" in run)

    assert "releases?per_page=100" in create
    assert "select(.tag_name" in create
    assert all("gh release view" not in run for run in runs)


def test_pinned_versions_agree_across_ci_and_metadata() -> None:
    ci = _load("ci.yml")
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert core.PIN in matrix
    floor_prefix = f"3.{core.REQUIRED[1]}."
    assert any(str(version).startswith(floor_prefix) for version in matrix)

    macos = _load("macos.yml")
    setup = next(
        step
        for step in _steps(macos, "test")
        if "actions/setup-python" in str(step.get("uses", ""))
    )
    assert setup["with"]["python-version"] == core.PIN

    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == core.PIN
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == f">={core.REQUIRED[0]}.{core.REQUIRED[1]}"
