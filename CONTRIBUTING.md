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
python -m pytest --cov --cov-fail-under=90
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
required check, so read the run rather than the badge: a queued Windows cell is
not green. macOS runs on `main`, tags and a weekly schedule, not on pull
requests. A green tag run is the strongest evidence for a release.

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

Releases are draft-first because GitHub release immutability is enabled: assets
cannot be attached after a release is published. Build and attach them while
the release is still a draft, verify, then publish the draft.

1. Merge the version bump (`pyproject.toml`, `__init__.py`, the changelog entry
   and `docs/releases/<version>.md`) to `main` with all checks green.
2. From a clean `main`, run the release check and create the annotated tag:

   ```bash
   git pull --ff-only
   python scripts/release_check.py
   git tag -a v<version> -m "python-mcp-bootstrap v<version>"
   git push origin v<version>
   ```

3. Prepare the draft. This builds with the pinned backend, writes
   `SHA256SUMS`, creates or reuses a **draft** release, uploads the assets,
   attests provenance, signs every artifact, and re-runs the release check
   against the draft. It never publishes the release and never talks to PyPI.

   ```bash
   gh workflow run prepare-release.yml --ref main -f tag=v<version>
   gh run watch <run-id>
   gh release view v<version> --json isDraft,assets \
     --jq '{draft:.isDraft, assets:[.assets[].name]}'
   ```

   The draft must have exactly seven assets: wheel, sdist, `SHA256SUMS`, three
   `.sigstore.json` bundles, and `provenance.intoto.jsonl`.

4. Verify the draft before flipping it:

   ```bash
   gh release download v<version> --dir /tmp/release-check \
     --pattern '*.whl' --pattern '*.tar.gz' --pattern SHA256SUMS
   (cd /tmp/release-check && sha256sum -c SHA256SUMS)
   gh attestation verify /tmp/release-check/*.whl \
     --repo 4zhmv6zvj2-afk/python-mcp-bootstrap
   python scripts/release_check.py --tag v<version>
   ```

   Do not publish on partial success.

5. Publish the draft. This is irreversible: it makes the release immutable and
   locks the tag.

   ```bash
   gh release edit v<version> --draft=false --latest
   ```

   Publishing fires `publish.yml`, which downloads the published assets,
   verifies checksums, signatures and provenance, runs the final
   `release_check --tag`, and only then publishes to PyPI under the `pypi`
   environment. It has no permission to modify release assets.

6. Never hand-attach assets, never publish a draft before every check passes,
   and do not edit a published release: GitHub refuses asset changes there. If
   a step fails before PyPI, fix and re-run the workflow; the version is not
   consumed until PyPI accepts it. If PyPI accepts and something later fails,
   the next version fixes it.

`sign-release.yml` remains for mutable or draft releases created outside this
flow; it cannot modify an immutable release.

Never upload test artifacts to real PyPI: a deleted release permanently
reserves its filenames, so a rehearsal upload can burn a version number for
good. Use TestPyPI for upload rehearsals and the draft-first flow above for
real releases.

Before tagging, confirm the version has never been uploaded: with project
owner access, open the project's Manage → History page and check that no
`Version <x.y.z> created` row exists. PyPI permanently reserves filenames
from deleted releases, and
`https://pypi.org/pypi/<project>/<version>/json` returns 404 both for a
version that was never published and for one whose release was deleted, so
History is the only reliable check. If a row exists, use the next free
version number instead.

## Scope

The core owns interpreter selection, consent, provisioning, verification, and
handoff. MCP server behavior and consumer-specific install steps belong in the
consumer repositories.
