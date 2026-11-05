# Consumer integration

Consumers pin a released version of this repository and vendor
`src/python_mcp_bootstrap/core.py`. The vendored file is committed with a
manifest so drift is visible in review.

A runnable example lives in [`examples/first_run.py`](../examples/first_run.py).
It imports a vendored `_vendor/python_mcp_bootstrap.py`; CI generates that copy
with `scripts/vendor.py`, runs `--check`, and then runs the first-run wrapper
against real `uv` on Python 3.12.

## Vendor layout

```text
consumer/
├── src/<package>/_vendor/
│   ├── python_mcp_bootstrap.py   # copied core.py
│   └── VENDOR.json               # source tag, commit, sha256
└── first_run.py                  # tiny adapter, must run on older Python
```

`VENDOR.json` should record:

```json
{
  "name": "python-mcp-bootstrap",
  "version": "0.2.0",
  "tag": "v0.2.0",
  "commit": "<full commit>",
  "source": "https://github.com/4zhmv6zvj2-afk/python-mcp-bootstrap",
  "file": "python_mcp_bootstrap.py",
  "sha256": "<sha256 of the vendored file>"
}
```

## Consumer adapter

The consumer imports the vendored core and passes its own app-specific values:

```python
from _vendor.python_mcp_bootstrap import BootstrapSpec, bootstrap


def continue_setup(args: list[str]) -> int:
    # The consumer's installer continues here.
    del args
    return 0


SPEC = BootstrapSpec(
    app="example-mcp",
    entrypoint="first_run.py",
    env_var="EXAMPLE_MCP_INTERPRETER",
    verify_import="example_mcp",
    package_main=continue_setup,
)
```

`package_main` is required for a safe in-process continuation. Bootstrap hands
off once and records the chosen interpreter in `spec.env_var`; a later pass
that arrives with the variable set and no continuation gets a
`missing_continuation` report (exit `7`) instead of another exec. A wrapper
that branches on `spec.env_var` and skips `bootstrap()` after the handoff still
works.

The example uses a top-level `_vendor/`; if your layout is
`src/<package>/_vendor/`, adjust the import. If the pre-install path exposes
the file as `python_mcp_bootstrap`, that import also works. Keep `VENDOR.json`
beside the vendored file.

`install_args` are consumer-controlled. Path-like entries are rejected when
the spec is built if they are absolute, Windows-rooted (including drive-relative
`C:tmp`), contain `..`, or use a `file:` URL, including attached short values
(`-t/tmp/x`) and `--flag=file:///...` forms. Venv- or system-redirecting flags
(`--target`, `--prefix`, `--root`, `--python`, `--system`,
`--break-system-packages`, and short forms) are rejected, and value-taking long
flags must be passed as `--flag=VALUE` so they cannot swallow the `--python`
that the bootstrap appends. Non-path flags such as `--index-url=https://...`
pass through; credentials in reports are masked. The bootstrap passes the list
to `uv pip install` directly and never uses a shell.

For a source distribution, the adapter imports the vendored file rather than a
Git dependency. The vendor step keeps the pre-install path auth-free.

`requirements` is the upstream form of the hash-pinned runtime install that
consumers used to patch into the vendored core. Pass project-relative
requirement files and the core installs them first, then installs the project
with `--no-deps`:

```python
SPEC = BootstrapSpec(
    app="example-mcp",
    entrypoint="first_run.py",
    env_var="EXAMPLE_MCP_INTERPRETER",
    requirements=("requirements-runtime.txt",),
    verify_import="example_mcp",
    package_main=continue_setup,
)
```

A missing or mismatched requirements file returns
`runtime_requirements_failed` before the project install starts. Paths are
validated with the same project-local rule as the other bootstrap paths.

## Python floor and vendoring

The package floor is Python 3.12: `requires-python = ">=3.12"`, and the core
checks `sys.version_info >= (3, 12)`. A consumer may raise
`BootstrapSpec.required` when it needs a newer interpreter, but the package
itself supports 3.12.

Vendoring `core.py` remains the recommended pattern for pre-install wrappers,
not a workaround for the package floor. It keeps the first-run path auth-free
and independent of pip or PyPI, so the wrapper imports before the application's
dependencies exist. Vendored code is held to 3.12 syntax and standard library
only, which is why the core imports nothing outside the stdlib and never
imports the MCP SDK.

## Updating

1. Tag and release this repository.
2. Run the consumer's vendor script from a checkout of the new tag.
3. Commit the copied core and the new `VENDOR.json`; do not add a local patch.
4. Run the consumer's full test suite on the 3.12–3.15 lines.
