# Changelog

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
