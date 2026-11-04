# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting

Report privately through GitHub's private vulnerability reporting:

https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/security/advisories/new

That reaches the maintainer privately and keeps the report out of the public
timeline. We aim to acknowledge a report within 10 business days (14 calendar
days), agree a disclosure timeline with the reporter, and publish an advisory
alongside the fix.

If neither channel works for you, open a minimal public issue saying only that
you have a security report and how to reach you. Do not put credentials,
tokens, or exploit details in a public issue.

## Bootstrap-specific guarantees

- The bootstrap does not download Python unless the caller passes the explicit
  `--install-python` consent flag.
- The bootstrap never runs `curl | sh`; if uv is missing it returns a human
  `tip` with the official uv installation docs link and stops. That tip is
  never executed.
- The bootstrap never modifies the system Python or its site-packages.
- The bootstrap does not use `shell=True` and has no shell executor.
- A project `.venv` from another interpreter is moved aside, not deleted.
- Credential-shaped values (URL userinfo on any scheme, key/value fields, and
  Bearer headers) in command arguments and captured output are redacted before
  they enter a report.
- Project-local paths and path-like `install_args` may not escape the project
  root (absolute, Windows-rooted, and `..` values are rejected before any
  subprocess starts, including attached short flag forms). Venv-redirecting
  flags (`--target`, `--prefix`, `--root`, `--python`) are rejected.
- Path checks are lexical: they do not resolve symlinks. A symlink inside the
  project can still point outside; the consumer owns that boundary.
- Concurrent first runs are not supported; there is no lock around the
  `.venv` move or the provisioning steps.
- `root` is the consumer's project directory and the working directory for
  every step; the bootstrap never works outside it on its own.
- The `verify_import` check runs in isolated mode (`-I -P`), so the project
  cwd, script directory, and `PYTHONPATH` cannot satisfy it.
- Release tags are annotated. Tags are unsigned for now. An unsigned tag is not
  a signature; verify release artifacts by digest when that matters.

A change that weakens any of these properties requires review before merge.
