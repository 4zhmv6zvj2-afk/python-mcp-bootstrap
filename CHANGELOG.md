# Changelog

## 0.1.5 — 2026-11-05

First installable release after PyPI 0.1.2. The code is identical to 0.1.3;
only the version string differs.

An earlier iteration of this repository published 0.1.3 and 0.1.4 through
trusted publishing. Those releases were deleted when the repository history
was replaced, and PyPI permanently reserves the filenames of deleted releases.
As a result:

- `v0.1.3` remains a GitHub-only release with its verified assets (wheel,
  sdist, `SHA256SUMS`, three Sigstore signature bundles and build provenance);
  it was never published to PyPI.
- The `0.1.4` version number cannot be uploaded either, so it is skipped
  entirely.
- `0.1.5` is the first version whose filenames are free, which is why the
  number jumps from 0.1.2 on PyPI.

See the 0.1.3 section for the actual changes: the extracted-sdist suite fix,
the install-argument ordering fix, and the pipeline and documentation
corrections. Users upgrading from the PyPI 0.1.2 artifacts get all of those,
including an sdist whose bundled tests pass.

## 0.1.3 — 2026-11-05

Patch release: the first sdist whose bundled test suite passes, plus a
structural fix to install-argument ordering.

### Fixed

- The `v0.1.2` sdist could not run its own test suite. It omitted
  `requirements-ci.txt` and `requirements-build.txt`, and
  `tests/test_workflows.py` read `.github/workflows` even outside a repository
  checkout. The sdist now ships both pinned requirement files,
  repository-only workflow tests skip when `.github/` is absent, and CI runs
  the extracted-sdist suite so this cannot regress. `v0.1.3` is the first
  sdist whose bundled tests pass; users of the `v0.1.2` sdist should upgrade.
- Install-argument ordering: the provisioning command is now
  `uv pip install --python <venv python> <install_args>`, so a trailing
  consumer-supplied flag can no longer swallow the appended interpreter
  argument. The `install_args` validation rules are unchanged.

### Pipeline

- `publish.yml` verifies build provenance for the sdist as well as the wheel.
- CI builds the wheel and sdist with `--no-isolation` using the pinned backend,
  matching the release build instead of silently re-resolving.
- Removed the dead wait loop from `release-gate.yml`: assets exist before
  publication now, so the gate verifies immediately.

### Docs

- README and CONTRIBUTING corrections: `v0.1.2` is named as the first release
  with provenance, and macOS is documented as running on `main`, tags and a
  weekly schedule rather than on pull requests.

## 0.1.2 — 2026-11-05

First published release of the hardened 0.1.x line. `v0.1.1` was tagged but
never published: after its initial immutable release was deleted, GitHub
refused to bind a new release to that tag name, so the same content ships here
under a fresh tag. The `v0.1.1` tag is kept as history only.

### Added

- Draft-first release pipeline: `prepare-release.yml` builds with the pinned
  backend, writes `SHA256SUMS`, creates a draft release, uploads the wheel,
  sdist, checksums, Sigstore signature bundles and a signed build-provenance
  attestation, and verifies the draft. Publishing the draft fires
  `publish.yml`, which re-verifies the published assets (checksums, signatures,
  provenance) and publishes to PyPI last. The publishing workflow has no
  permission to modify release assets.
- Failure result `exec_failed` (exit `8`) when the chosen interpreter cannot be
  started; JSON report with a redacted `detail`, never a traceback.
- A `provision_failed` report carries a `tip` when the installed uv is older
  than 0.13 and may not resolve the pinned interpreter.
- Hash-pinned build, test, and uv requirements files, plus a
  `.pre-commit-config.yaml` running the same ruff checks as CI.

### Changed

- `BootstrapSpec` is genuinely frozen: `required` and `install_args` are copied
  to tuples and validated at construction; `required` raises `ValueError` for
  bad lengths, non-integers, booleans, or non-sequences.
- Credential redaction covers URL userinfo on any scheme (including passwords
  containing `/`), `Authorization`/`Proxy-Authorization` headers (Basic, Bearer,
  Token, Digest), and prefixed/suffixed credential keys such as
  `AWS_SECRET_ACCESS_KEY` and `MY_API_KEY`.
- `verify_import` is checked on every interpreter branch, including an explicit
  `--python`; an explicit interpreter that cannot import the app reports
  `verify_import_failed` (exit `5`), and a running interpreter that cannot
  import it returns `needs_install` instead of reporting success.
- `install_args` reject `--system`/`--break-system-packages`, `file:` URLs
  (including inside `--flag=...`), drive-relative Windows paths such as
  `C:tmp`, and value-taking long flags passed without `=`.
- The release gate downloads and verifies published assets: `SHA256SUMS`
  against the bytes, plus signature bundles and provenance. `SHA256SUMS` uses
  plain filenames; both the checker and the workflow tolerate a leading `./`.
- The extracted sdist contains `.python-version`; CI now runs the extracted
  sdist suite (repository-only workflow tests are skipped when `.github/` is
  absent).

### Docs

- Python-floor split documented: PyPI installs require 3.14+; Python 3.12/3.13
  consumers vendor `core.py`.
- Package metadata adds authors, maintainers, and Issues/README project URLs.
- Contract, integration, and CONTRIBUTING release docs match the implemented
  selection/provisioning order, exit codes, `install_args` rules, and the
  draft-first release flow.

## 0.1.1 — 2026-11-05

Tagged but never published (see 0.1.2). Kept in the changelog for the record.

Patch release: behavior fixes and a release pipeline that produces verified,
checksummed, signed artifacts.

### Added

- Release artifacts now carry `SHA256SUMS` (generated by the publish workflow),
  Sigstore `.sigstore.json` signature bundles, and a signed build-provenance
  attestation (`provenance.intoto.jsonl`), attached to the GitHub release before
  PyPI publishing.
- Failure result `exec_failed` (exit `8`) when the chosen interpreter cannot be
  started; the report is JSON with a redacted `detail`, not a traceback.
- A `provision_failed` report now carries a `tip` when the installed uv is older
  than 0.13 and may not resolve the pinned interpreter.
- Hash-pinned build, test, and uv requirements files, plus a `.pre-commit-config.yaml`
  running the same ruff checks as CI.

### Changed

- `BootstrapSpec` is actually frozen: `required` and `install_args` are copied
  to tuples during construction and validated there; a list passed by the
  caller can no longer mutate a validated spec. `required` must be a 3-integer
  sequence and raises `ValueError` for bad lengths, non-integers, booleans, or
  non-sequences.
- Credential redaction covers URL userinfo on any scheme (including passwords
  containing `/`), `Authorization`/`Proxy-Authorization` headers (Basic, Bearer,
  Token, Digest), and credential-shaped names with prefixes/suffixes such as
  `AWS_SECRET_ACCESS_KEY` and `MY_API_KEY`.
- `verify_import` is now checked on every interpreter branch, including an
  explicit `--python`; an explicit interpreter that cannot import the app
  reports `verify_import_failed` (exit `5`), and a running interpreter that
  cannot import it returns the repair card (`needs_install`) instead of
  reporting success.
- `install_args` additionally reject `--system` and `--break-system-packages`,
  `file:` URLs (including inside `--flag=...`), drive-relative Windows paths
  such as `C:tmp`, and value-taking long flags passed without `=`, which could
  otherwise swallow the appended `--python`.
- The release gate now verifies the published assets instead of only their
  names: it downloads the wheel/sdist, checks `SHA256SUMS` against the bytes,
  and requires the signature bundles and provenance. PyPI publishing is the last
  publish step, so an earlier failure leaves the version unconsumed.
- The extracted sdist now contains `.python-version`; its test suite no longer
  fails outside a git checkout.

### Docs

- The Python-floor split is stated explicitly: PyPI installs require 3.14+, and
  Python 3.12/3.13 consumers vendor `core.py`.
- Package metadata now includes authors, maintainers, and Issues/README
  project URLs.
- Contract documentation matches the implemented selection and provisioning
  order, the new exit codes, and the hardened `install_args` rules.

## 0.1.0 — 2026-11-04

First release of the shared pre-install Python bootstrap for MCP applications.

- `BootstrapSpec`, version parsing, platform-aware venv paths, and uv discovery
  in a single stdlib-only `core.py` that stays importable on Python 3.12.
- Selection order (`--python`, the running interpreter, an existing `.venv`,
  then the consent card), explicit `--install-python` consent before any
  download, project-local provisioning, install verification, atomic pin
  writes, and exec handoff.
- The good-running path hands off once and records the chosen interpreter in
  `spec.env_var`. A later pass that arrives with that variable set and no
  continuation reports `missing_continuation` (exit `7`) instead of
  re-executing the entry point; a wrapper that branches on `spec.env_var`
  continues normally.
- Windows-aware handoff and uv discovery, managed-only interpreter selection,
  project-path validation, `--` argument handling, and credential-redacted
  diagnostics.
- `install_args` reject path-like entries (absolute, Windows-rooted, `..`, and
  attached short forms) and venv-redirecting flags (`--target`, `--prefix`,
  `--root`, `--python`); non-path flags such as `--index-url` pass through.
- `pin` is a plain `X[.Y[.Z]]` final version at or above `required`.
- A broken or mismatched `.venv` is moved aside, never deleted, and
  `verify_import` runs isolated (`-I -P`).
- Vendor tooling (`scripts/vendor.py`) with `VENDOR.json` manifests and a
  `--check` drift test, plus the vendored example first run in CI.
- `scripts/release_check.py` validates metadata, changelog, release notes, the
  Python pin, tracked-file hygiene, annotated tags, and published release
  assets.
- CI on Python 3.14.10 and 3.15.2 on Ubuntu, macOS, and Windows, plus a 3.12
  compatibility job, a wheel/release gate, and the vendored example first run.
- Distribution on PyPI via OIDC trusted publishing, with GitHub Actions pinned
  to commit SHAs and the wheel, sdist, and `SHA256SUMS` attached to the GitHub
  release.
- Development pin 3.15.2 and MIT license.
- Honest limits: path checks are lexical (symlinks are not resolved), and
  concurrent first runs against one project are unsupported.
