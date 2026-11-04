## What changed

## Checklist

- [ ] `python scripts/release_check.py` on a clean tree
- [ ] `python -m pytest --cov --cov-fail-under=90`
- [ ] `python -m ruff format --check` and `python -m ruff check`
- [ ] `python -m mypy`
- [ ] `python -m build --no-isolation`; extracted-sdist suite passes

Release PRs only:

- [ ] The version has no `Version <x.y.z> created` row in the project's
      Manage → History page (PyPI reserves deleted filenames permanently;
      a 404 from `/pypi/<project>/<version>/json` proves nothing)
- [ ] Annotated tag; `prepare-release` draft has exactly seven assets
- [ ] Manual draft gate: checksums, both attestations, draft-sdist suite,
      release body matches `docs/releases/<version>.md`
- [ ] Draft flipped only after the gate; PyPI publish is the last workflow step
