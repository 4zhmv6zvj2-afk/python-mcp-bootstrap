"""Workflow guardrails: preparing artifacts and publishing them stay separate."""

from __future__ import annotations

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_publish_workflow_cannot_modify_release_assets() -> None:
    text = _workflow("publish.yml")

    assert "gh release upload" not in text
    assert "contents: write" not in text
    assert "environment: pypi" in text
    assert "packages-dir: pypi-dist/" in text
    assert "gh release download" in text
    assert text.index("python scripts/release_check.py") < text.index(
        "Publish with OIDC trusted publishing"
    )


def test_prepare_release_attaches_assets_only_to_a_draft() -> None:
    text = _workflow("prepare-release.yml")

    assert "--draft" in text
    assert "gh release upload" in text
    assert "contents: write" in text
    assert "gh-action-pypi-publish" not in text
    assert "environment: pypi" not in text


def test_publish_requires_a_published_immutable_release() -> None:
    text = _workflow("publish.yml")

    assert "still a draft" in text
    assert "not immutable" in text
    assert "immutable" in text


def test_prepare_release_detects_existing_drafts() -> None:
    """gh release view cannot see drafts; the list endpoint must be used."""

    text = _workflow("prepare-release.yml")

    assert "gh release view" not in text
    assert "releases?per_page=100" in text
    assert "select(.tag_name" in text
