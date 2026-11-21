"""Version policy guard: one floor, minor-line CI, exact product pin."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML
from scripts import release_check

ROOT = release_check.ROOT
WORKFLOWS = ROOT / ".github" / "workflows"
CORE = ROOT / "src" / "python_mcp_bootstrap" / "core.py"

requires_workflows = pytest.mark.skipif(
    not WORKFLOWS.is_dir(),
    reason="workflow files are not shipped in the sdist",
)


def _policy() -> tuple[str, tuple[int, int, int]]:
    found = release_check._core_constants(CORE)
    assert found is not None
    return found


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
    """AC-boot-ver-1"""

    pin, required = _policy()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    floor = release_check._metadata_requires_python(required)
    assert required[2] == 0
    assert project["requires-python"] == floor
    assert re.fullmatch(rf">={required[0]}\.\d+", project["requires-python"])
    committed = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert committed == release_check._pin_line(pin)
    assert pin.startswith(committed + ".")


def test_committed_python_version_names_the_line() -> None:
    pin, _required = _policy()
    committed = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert committed == release_check._pin_line(pin)


@requires_workflows
def test_ci_matrix_uses_minor_lines() -> None:
    """AC-boot-ver-2"""

    pin, required = _policy()
    expected = release_check._ci_lines(required, pin)
    assert expected[0] == f"{required[0]}.{required[1]}"
    assert expected[-1] == release_check._pin_line(pin)
    assert expected == [
        f"{required[0]}.{minor}"
        for minor in range(required[1], int(release_check._pin_line(pin).split(".")[1]) + 1)
    ]
    ci = _load("ci.yml")
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert list(matrix) == expected
    assert all(re.fullmatch(rf"{required[0]}\.\d+", version) for version in matrix)

    moved_minor = int(release_check._pin_line(pin).split(".")[1]) + 1
    moved = f"{required[0]}.{moved_minor}.0"
    moved_lines = release_check._ci_lines(required, moved)
    assert moved_lines[:-1] == expected
    assert moved_lines[-1] == f"{required[0]}.{moved_minor}"


@requires_workflows
def test_test_jobs_track_the_latest_patch_and_record_it() -> None:
    ci = _load("ci.yml")
    for job in ("test", "py312-smoke", "example"):
        setup = _setup_python(ci, job)
        assert str(setup["with"].get("check-latest")) == "true"
        assert any("python -VV" in str(step.get("run", "")) for step in _steps(ci, job))


@requires_workflows
def test_smoke_and_example_jobs_follow_the_floor() -> None:
    """AC-boot-ver-3"""

    _pin, required = _policy()
    floor = f"{required[0]}.{required[1]}"
    ci = _load("ci.yml")
    for job in ("py312-smoke", "example"):
        setup = _setup_python(ci, job)
        assert setup["with"]["python-version"] == floor


@requires_workflows
def test_macos_uses_a_line_and_records_the_patch() -> None:
    pin, _required = _policy()
    macos = _load("macos.yml")
    setup = _setup_python(macos, "test")
    assert setup["with"]["python-version"] == release_check._pin_line(pin)
    assert str(setup["with"].get("check-latest")) == "true"
    assert any("python -VV" in str(step.get("run", "")) for step in _steps(macos, "test"))


@requires_workflows
def test_build_and_release_jobs_keep_exact_pins() -> None:
    pin, _required = _policy()
    ci = _load("ci.yml")
    for job in ("package", "sdist-suite"):
        setup = _setup_python(ci, job)
        assert setup["with"]["python-version"] == pin
        assert "check-latest" not in setup["with"]

    for workflow in ("prepare-release.yml", "publish.yml", "release-gate.yml"):
        document = _load(workflow)
        job = next(iter(document["jobs"]))
        setup = _setup_python(document, job)
        assert setup["with"]["python-version"] == pin


@requires_workflows
def test_workflow_files_keep_their_python_strings() -> None:
    """AC-boot-ver-4"""

    pin, required = _policy()
    floor = f"{required[0]}.{required[1]}"
    line = release_check._pin_line(pin)
    checker = Path(release_check.__file__).read_text(encoding="utf-8")
    assert ".github" not in checker
    quoted = (f'"{floor}"', f'"{line}"', f'"{pin}"')
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "core.py" not in text
        if "python-version:" in text:
            assert any(snippet in text for snippet in quoted)


def test_checker_runs_without_workflow_files(tmp_path: Path) -> None:
    """AC-boot-ver-5"""

    from tests.test_release_check import _release_tree

    _release_tree(tmp_path)
    assert not (tmp_path / ".github").exists()
    assert release_check.check(tmp_path, allow_dirty=True) == []
    compared = (
        test_ci_matrix_uses_minor_lines,
        test_smoke_and_example_jobs_follow_the_floor,
        test_workflow_files_keep_their_python_strings,
        test_macos_uses_a_line_and_records_the_patch,
        test_build_and_release_jobs_keep_exact_pins,
    )
    for test in compared:
        marks = getattr(test, "pytestmark", [])
        if not isinstance(marks, list):
            marks = [marks]
        skip = [mark for mark in marks if getattr(mark, "name", "") == "skipif"]
        assert skip
        assert "sdist" in skip[0].kwargs["reason"]


def test_version_reading_lives_in_the_release_checker() -> None:
    """AC-boot-ver-7"""

    assert release_check._core_constants.__module__ == "scripts.release_check"
    assert release_check._ci_lines.__module__ == "scripts.release_check"
    assert release_check._metadata_requires_python.__module__ == "scripts.release_check"
    names = {path.name for path in (ROOT / "scripts").glob("*.py")}
    assert "release_check.py" in names
    assert "version_policy.py" not in names


def test_handwritten_policy_prose_is_left_in_place() -> None:
    """AC-boot-ver-8"""

    paths = [
        ROOT / "docs" / "version-policy.md",
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
    ]
    before = {path: path.read_bytes() for path in paths}
    assert release_check.check(ROOT, allow_dirty=True) == []
    assert {path: path.read_bytes() for path in paths} == before
    checker = Path(release_check.__file__).read_text(encoding="utf-8")
    for name in ("version-policy.md", "README.md", "CONTRIBUTING.md"):
        assert name not in checker


def test_import_helper_stays_in_the_one_core_file() -> None:
    """AC-boot-ver-9"""

    package = ROOT / "src" / "python_mcp_bootstrap"
    core_path = package / "core.py"
    assert core_path.is_file()
    assert list(package.rglob("core.py")) == [core_path]
    source = core_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {"_installed", "bootstrap", "provision"} <= set(functions)

    def calls(name: str) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                found.add(node.func.id)
        return found

    assert "_installed" in calls("bootstrap")
    assert "_needs_install" in calls("bootstrap")
    assert "provision" in calls("bootstrap")
    assert "_installed" in calls("provision")
    assert "_failed" in calls("provision")
    assert "bootstrap" not in calls("provision")
