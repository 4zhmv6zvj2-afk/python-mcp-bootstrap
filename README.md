# python-mcp-bootstrap

[![ci](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/actions/workflows/ci.yml/badge.svg)](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/badge)](https://securityscorecards.dev/viewer/?uri=github.com/4zhmv6zvj2-afk/python-mcp-bootstrap)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/16336/badge)](https://www.bestpractices.dev/projects/16336)

A small setup helper for Python apps that use MCP.

MCP (Model Context Protocol) is a way for AI assistants to use tools and data.
Before one of those apps starts, this helper makes sure it runs on a supported
version of Python. If your computer does not have one, it explains what is
missing and asks before downloading anything. It never changes the Python that
is already installed.

This is a bootstrap *for* MCP applications, not an MCP implementation. It has
no runtime dependency on the MCP SDK and never imports one.

**Most people do not need to run this directly.** The app's setup script uses
it. If you are a developer adding it to an app, jump to
[For developers](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/README.md#for-developers).

## Why this is public

This helper runs before an app's dependencies exist, which means it executes
during someone else's setup. A tool in that position should be inspectable
rather than trusted on faith: the source is MIT-licensed, the PyPI wheel and
sdist are the same code published from this repository, and releases from
`v0.1.2` onward are checksummed, signed and attested (see
[release verification](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/README.md#verifying-releases)).
It makes no network calls of its own, has no telemetry, and has no runtime
dependency on the MCP SDK. After you pass `--install-python`, provisioning runs
`uv` to download the pinned interpreter and install the app's dependencies from
the package index you configured.

## Do I need this?

- If an app's setup tells you to run `python first_run.py`, that script uses
  this helper. Follow the app's instructions.
- If you are building or packaging an MCP app and need a first-run Python
  check, use this library.
- If you just want to run an app that is already set up, no.

## What it does

1. Looks for Python 3.12 or newer.
2. Looks for a working `.venv` in the project.
3. If the Python or the app environment is missing or incomplete, prints a
   JSON report with a `card` and a `next` command. Nothing is downloaded.
4. If you agree, the wrapper re-runs with `--install-python`, which installs
   what is missing inside the project.
5. Continues setup with that Python.

It can also check a Python you name:

```bash
python first_run.py --python /path/to/python
```

## What it will not do

- It will not download Python without `--install-python`.
- It will not change your system Python or system packages.
- It will not delete an existing `.venv`; a wrong one is moved aside.
- It will not run `curl | sh`. If `uv` is missing, it prints a tip with the
  official uv installation page and stops. It never runs that tip.
- It will not run commands through a shell.
- It masks credential-shaped values in its reports and captured output.

## For developers

This repository is a library, not the app. The command-line tool is a
diagnostic:

```bash
python -m python_mcp_bootstrap --check
python -m python_mcp_bootstrap --version
```

Install from PyPI:

```bash
python -m pip install python-mcp-bootstrap
```

PyPI installs require Python 3.12+. Vendoring `core.py` remains the recommended
pattern for pre-install wrappers (see
[Vendoring](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/README.md#vendoring)):
it is auth-free, needs no pip or PyPI at first run, and keeps the wrapper
importable before the app's dependencies exist. The core is kept to 3.12 syntax
and standard library only so it stays importable on the floor.

GitHub releases from `v0.1.2` onward attach the wheel, the sdist,
`SHA256SUMS`, Sigstore signature bundles (`.sigstore.json`), and a signed
build-provenance attestation to the
[releases page](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/releases). All are built from the same tagged tree, so
their digests match. `v0.1.0` predates the attestation step: it has
`SHA256SUMS` and the `.sigstore.json` signatures, but no
`provenance.intoto.jsonl`.

Version history as users see it on PyPI:
`v0.1.1` was tagged but never published. `v0.1.3` exists on GitHub only: PyPI
permanently reserves the filenames of a deleted release, and an earlier
iteration of this repository had published and removed that version. `v0.1.4`
was skipped for the same filename reason. `0.1.5` is the first installable
release after `0.1.2`, and `pip install python-mcp-bootstrap` resolves to the
newest release.

### Verifying releases

To verify a download:

```bash
sha256sum -c SHA256SUMS
gh attestation verify python_mcp_bootstrap-<version>-py3-none-any.whl \
  --repo 4zhmv6zvj2-afk/python-mcp-bootstrap   # releases from v0.1.2 onward
```

`gh attestation verify` checks the signed provenance record: which repository,
commit, workflow and builder produced the file. The `.sigstore.json` bundles
carry the matching keyless signatures for every release that has them; they can
also be checked manually with `cosign verify-blob`, while `gh attestation verify`
is the automated provenance path used by the release workflow.

Use `BootstrapSpec` and `bootstrap()` from an app's first-run wrapper:

```python
import sys
from pathlib import Path

from python_mcp_bootstrap import BootstrapSpec, bootstrap


def continue_setup(args: list[str]) -> int:
    # The rest of setup goes here.
    del args
    return 0


root = Path(__file__).resolve().parent
spec = BootstrapSpec(
    app="example-mcp",
    entrypoint="first_run.py",
    env_var="EXAMPLE_MCP_INTERPRETER",
    install_args=("-e", "."),
    verify_import="example_mcp",
    package_main=continue_setup,
)
raise SystemExit(bootstrap(sys.argv[1:], root, spec))
```

`package_main` is the function `bootstrap()` calls when the current Python is
already suitable. Pass it: an entry point that calls `bootstrap()`
unconditionally needs somewhere to continue.

The first pass may hand off once, and it records the chosen interpreter in
`spec.env_var`. A later pass that reaches `bootstrap()` with that variable
already set and no continuation gets a `missing_continuation` report (exit
`7`) instead of another exec, so the re-exec loop is gone. A wrapper that
branches on `spec.env_var` and skips `bootstrap()` after the handoff keeps
working, which is what the variable is for.

`bootstrap()` checks `--python`, the current interpreter, and an existing
`.venv`, in that order. It only offers to install the pinned Python after
`--install-python`. An existing `.venv` is also checked with `verify_import`;
the check runs isolated (`-I -P`), so only that venv's installed packages
count. If the app or MCP module is missing, the repair card asks for
`--install-python` before running the installer.

`install_args` are consumer-controlled. Path-like entries are rejected when
the spec is built if they are absolute, Windows-rooted, or contain `..`,
including attached short-option values (`-t/tmp/x`). Venv-redirecting flags
(`--target`, `--prefix`, `--root`, `--python` and their short forms) are
rejected. Non-path flags such as `--index-url` pass through; credentials in
reports are masked.

`requirements` is an optional tuple of project-relative, hash-pinned
requirement files. When set, provisioning first runs
`uv pip install --require-hashes -r <file>` for each entry, then installs the
project with `--no-deps`; a failed hash check returns
`runtime_requirements_failed` before the project install starts. This is the
upstream form of the feature consumers used to patch into the vendored core.

The core is one stdlib-only file, `core.py`. It must stay importable on Python
3.12 because it runs before the app's dependencies are installed; 3.12 is also
the supported floor, and CI runs the suite on the 3.12–3.15 lines.

### Vendoring

Consumers copy `core.py` and a `VENDOR.json` manifest instead of taking a
runtime dependency:

```bash
python scripts/vendor.py \
  --target /path/to/consumer \
  --dest src/example/_vendor/python_mcp_bootstrap.py
```

Use `--check` to verify a pinned copy. The example app vendors `core.py` into
`examples/_vendor/` and CI runs the same `vendor.py --check` sequence.

The vendoring tool (`scripts/vendor.py`) ships in the source tree, not in the
wheel: vendoring requires a source checkout. A PyPI install provides the
contract and the diagnostic CLI, not the vendor command.

- Contract: [docs/contract.md](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/docs/contract.md)
- Integration details: [docs/integration.md](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/docs/integration.md)
- Version policy: [docs/version-policy.md](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/docs/version-policy.md)
- Example first run: [examples/first_run.py](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/examples/first_run.py)
- Changelog: [CHANGELOG.md](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/CHANGELOG.md)
- Contributing and release checks: [CONTRIBUTING.md](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/CONTRIBUTING.md)

## Development

Requires Python 3.12+. The committed toolchain line is 3.15
(`.python-version`); the package floor is 3.12; build and release jobs pin
3.15.2.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest --cov --cov-fail-under=90
python -m ruff format --check
python -m ruff check
python -m mypy
python -m build
```

CI runs the suite on the 3.12, 3.13, 3.14 and 3.15 lines on Ubuntu and
Windows (each runner resolves the latest patch; the job prints `python -VV`),
plus a wheel/release gate, an extracted-sdist suite, and the vendored example
first run.
`main` is protected: the release gate, the 3.12 job, the vendored example
run, and the CodeQL analysis jobs are required before a merge, and
force-pushes and deletions are blocked.
The macOS 15 job (`.github/workflows/macos.yml`) runs the same suite on pushes
to `main`, on tags, and weekly, but not on pull requests: GitHub's macOS arm64
pool is capacity-constrained and must not gate merges. An extracted-sdist suite
(job `sdist-suite`) runs on every pull request and checks that the sdist's own
bundled tests pass; it is not a required branch-protection check, so read the
run rather than the badge.

## License

MIT. See [LICENSE](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/blob/main/LICENSE).
