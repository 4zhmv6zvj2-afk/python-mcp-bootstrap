"""Example wrapper tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def test_example_explains_missing_vendor(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "examples" / "first_run.py"
    target = tmp_path / "first_run.py"
    shutil.copyfile(source, target)

    result = subprocess.run(
        [sys.executable, str(target)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "vendored core is missing" in result.stderr
    assert "scripts/vendor.py" in result.stderr
