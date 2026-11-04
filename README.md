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
[For developers](#for-developers).

## Do I need this?

- If an app's setup tells you to run `python first_run.py`, that script uses
  this helper. Follow the app's instructions.
- If you are building or packaging an MCP app and need a first-run Python
  check, use this library.
- If you just want to run an app that is already set up, no.

## What it does

1. Looks for Python 3.14 or newer.
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

PyPI installs require Python 3.14+. On Python 3.12 or 3.13 the package cannot be
pip-installed; vendoring `core.py` is the supported path there (see
[Vendoring](#vendoring)) — `core.py` is deliberately kept to 3.12 syntax and
stdlib only for exactly that case.

Releases from `v0.1.1` onward attach the wheel, the sdist, `SHA256SUMS`,
Sigstore signature bundles (`.sigstore.json`), and a signed build-provenance
attestation to the
[releases page](https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap/releases).
All are built from the same tagged tree, so their digests match. `v0.1.0`
predates the attestation step: it has `SHA256SUMS` and the `.sigstore.json`
signatures, but no `provenance.intoto.jsonl`.

To verify a download:

```bash
sha256sum -c SHA256SUMS
gh attestation verify python_mcp_bootstrap-<version>-py3-none-any.whl \
  --repo 4zhmv6zvj2-afk/python-mcp-bootstrap   # releases from v0.1.1 onward
```

`gh attestation verify` checks the signed provenance record: which repository,
commit, workflow and builder produced the file. The `.sigstore.json` bundles
carry the matching keyless signatures for every release that has them.

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

The core is one stdlib-only file, `core.py`. It must stay importable on Python
3.12 because it runs before the app's dependencies are installed; CI runs the
suite on 3.12 as well as on the supported 3.14 and 3.15 interpreters.

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

- Contract: [docs/contract.md](docs/contract.md)
- Integration details: [docs/integration.md](docs/integration.md)
- Example first run: [examples/first_run.py](examples/first_run.py)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Contributing and release checks: [CONTRIBUTING.md](CONTRIBUTING.md)

## Development

Requires Python 3.14+. The development pin is 3.15.2.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest --cov=python_mcp_bootstrap --cov-fail-under=90
python -m ruff format --check
python -m ruff check
python -m mypy
python -m build
```

CI targets Python 3.14.10 and 3.15.2 on Ubuntu and Windows, plus a 3.12
compatibility job, a wheel/release gate, and the vendored example first run.
`main` is protected: the release gate, the 3.12 job, and the vendored example
run are required before a merge, and force-pushes and deletions are blocked.
The macOS 15 job (`.github/workflows/macos.yml`) runs the same suite on pushes
to `main`, on tags, and weekly, but not on pull requests: GitHub's macOS arm64
pool is capacity-constrained and must not gate merges.

## License

MIT. See [LICENSE](LICENSE).
