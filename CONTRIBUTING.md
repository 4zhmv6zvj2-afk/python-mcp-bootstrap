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

## Tests for new functionality

New functionality lands with tests. The suite runs in CI with a 90% line
coverage floor (`--cov-fail-under=90`), so behaviour added without tests fails
the build; a change that fixes a bug should include a regression test.

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

The `publish` workflow builds, checksums, signs, attests and uploads the
artifacts, then publishes to PyPI last — so a failure before the PyPI step
leaves the version unconsumed and the workflow re-runnable.

Before tagging, from the commit that will be tagged:

```bash
python -m pip install --require-hashes -r requirements-build.txt
python scripts/release_check.py
python -m pytest --cov=python_mcp_bootstrap --cov-fail-under=90
python -m build --no-isolation
```

Then create the annotated tag and the GitHub release:

```bash
git tag -a v<version> -m "python-mcp-bootstrap v<version>"
git push origin v<version>
gh release create v<version> --notes-file docs/releases/<version>.md
```

Publishing the release triggers the workflow, which:

1. rebuilds the wheel and sdist from the tagged tree with the pinned backend
   (`python -m build --no-isolation`),
2. writes `dist/SHA256SUMS`,
3. uploads the wheel, sdist and `SHA256SUMS` to the release,
4. attests build provenance and writes `dist/provenance.intoto.jsonl`,
5. signs every artifact with Sigstore (`.sigstore.json`) and uploads the
   bundles plus the provenance file,
6. re-runs `python scripts/release_check.py --tag v<version>` as the final gate
   (it downloads the assets and verifies the checksums, signatures and
   provenance are present),
7. publishes to PyPI with OIDC trusted publishing.

Do not hand-attach assets and do not create a release before the checks above
pass. If a step fails before PyPI publishing, fix and re-run the workflow
(`gh workflow run publish.yml -f tag=v<version>`); the version is not consumed
until PyPI accepts it. Tags stay deliberately unsigned: artifact signatures and
provenance live in the release assets, and a tag is not a signature.

## Scope

The core owns interpreter selection, consent, provisioning, verification, and
handoff. MCP server behavior and consumer-specific install steps belong in the
consumer repositories.
