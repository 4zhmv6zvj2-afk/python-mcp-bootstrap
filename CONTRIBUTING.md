# Contributing

## Setup

The development pin is Python 3.15.2. The package floor is 3.14.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Checks

Run all four before proposing a change:

```bash
python -m pytest --cov=python_mcp_bootstrap --cov-fail-under=90
python -m ruff format --check
python -m ruff check
python -m mypy
```

Build the distribution as a final packaging check:

```bash
python -m build
```

Exercise the vendored consumer path as CI does:

```bash
python scripts/vendor.py --target examples --dest _vendor/python_mcp_bootstrap.py
python scripts/vendor.py --target examples --dest _vendor/python_mcp_bootstrap.py --check
```

## CI status

`main` is protected. The wheel/release gate, the Python 3.12 import job, and
the vendored example run are required status checks before a pull request
merges, and force-pushes and branch deletions are blocked.

The 3.14/3.15 matrix runs alongside those required jobs, but it is not a
required check, so read the run rather than the badge: a queued macOS or
Windows cell is not green. A green tag run is the strongest evidence for a
release.

## Rules

- `src/python_mcp_bootstrap/core.py` stays stdlib-only.
- `core.py` must remain importable and runnable on Python 3.12; CI runs the
  suite on 3.12 as well as on the 3.14 and 3.15 matrix.
- Never import `mcp` from the bootstrap path.
- Never add an install, download, or provisioning subprocess before explicit
  consent. Version probes and the isolated import check may run before consent.
- Never use `shell=True`.
- Keep machine-specific paths, credentials, and private labels out of tracked
  files.

## Release

Before tagging, from the commit that will be tagged:

```bash
python scripts/release_check.py
python -m pytest --cov=python_mcp_bootstrap --cov-fail-under=90
python -m build
```

Rebuild `dist/` from that tip (`dist/` is gitignored), regenerate
`dist/SHA256SUMS` for the wheel and sdist, and verify the wheel in a clean
environment before attaching them:

```bash
python -m venv /tmp/wheel-check
/tmp/wheel-check/bin/python -m pip install dist/*.whl
/tmp/wheel-check/bin/python -m python_mcp_bootstrap --check
```

Tag with an annotated tag, push it, and attach the wheel and sdist to the
GitHub release:

```bash
git tag -a v<version> -m "python-mcp-bootstrap v<version>"
git push origin v<version>
python scripts/release_check.py --tag v<version>
```

Use annotated tags for releases. CI’s package job fails a tag/version mismatch
and a lightweight tag when the tag is present; the `release-gate` workflow
verifies the published release’s wheel, sdist, and `SHA256SUMS` assets. The
release notes live in `docs/releases/`. Tags are unsigned for now; do not
present a tag as a signature.

## Scope

The core owns interpreter selection, consent, provisioning, verification, and
handoff. MCP server behavior and consumer-specific install steps belong in the
consumer repositories.
