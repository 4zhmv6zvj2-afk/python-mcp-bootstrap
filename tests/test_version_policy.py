"""Version policy guard: one floor, minor-line CI, exact product pin."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from python_mcp_bootstrap import core

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYTHON_LINES = ["3.12", "3.13", "3.14", "3.15"]
PIN_LINE = ".".join(core.PIN.split(".")[:2])

requires_workflows = pytest.mark.skipif(
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


def _setup_python(document: dict[str, Any], job: str) -> dict[str, Any]:
    return next(
        step
        for step in _steps(document, job)
        if "actions/setup-python" in str(step.get("uses", ""))
    )


def test_metadata_floor_is_a_minor_line() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert core.REQUIRED == (3, 12, 0)
    assert project["requires-python"] == ">=3.12"
    assert project["requires-python"] == f">={core.REQUIRED[0]}.{core.REQUIRED[1]}"
    assert re.fullmatch(r">=3\.\d+", project["requires-python"])


def test_committed_python_version_names_the_line() -> None:
    committed = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert committed == PIN_LINE == "3.15"
    assert core.PIN == "3.15.2"


@requires_workflows
def test_ci_matrix_uses_minor_lines() -> None:
    ci = _load("ci.yml")
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert matrix == PYTHON_LINES
    assert all(re.fullmatch(r"3\.\d+", version) for version in matrix)


@requires_workflows
def test_test_jobs_track_the_latest_patch_and_record_it() -> None:
    ci = _load("ci.yml")
    for job in ("test", "py312-smoke", "example"):
        setup = _setup_python(ci, job)
        assert str(setup["with"].get("check-latest")) == "true"
        assert any("python -VV" in str(step.get("run", "")) for step in _steps(ci, job))


@requires_workflows
def test_macos_uses_a_line_and_records_the_patch() -> None:
    macos = _load("macos.yml")
    setup = _setup_python(macos, "test")
    assert setup["with"]["python-version"] == PIN_LINE
    assert str(setup["with"].get("check-latest")) == "true"
    assert any("python -VV" in str(step.get("run", "")) for step in _steps(macos, "test"))


@requires_workflows
def test_build_and_release_jobs_keep_exact_pins() -> None:
    ci = _load("ci.yml")
    for job in ("package", "sdist-suite"):
        setup = _setup_python(ci, job)
        assert setup["with"]["python-version"] == core.PIN
        assert "check-latest" not in setup["with"]

    for workflow in ("prepare-release.yml", "publish.yml", "release-gate.yml"):
        document = _load(workflow)
        job = next(iter(document["jobs"]))
        setup = _setup_python(document, job)
        assert setup["with"]["python-version"] == core.PIN
