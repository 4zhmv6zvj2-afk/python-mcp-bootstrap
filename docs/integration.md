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
  "version": "0.1.0",
  "tag": "v0.1.0",
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

## Why not a pip dependency

A first-run entry point may execute on Python 3.12, before the application's
dependencies are installed. A package whose metadata says `requires-python
>=3.14` cannot be installed in that environment. Vendoring a stdlib-only core
solves the ordering problem and keeps an auth-free install working without
GitHub credentials.

## Updating

1. Tag and release this repository.
2. Run the consumer's vendor script with the new tag.
3. Commit the copied core and the new `VENDOR.json`.
4. Run the consumer's full test suite on 3.14 and 3.15, plus a core smoke on
   3.12.
