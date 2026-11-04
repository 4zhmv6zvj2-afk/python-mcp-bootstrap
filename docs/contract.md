# Bootstrap contract

This is the contract for the bootstrap selection, consent, provisioning,
verification, and handoff path.

## Inputs

`bootstrap(args, root, spec, ...)` accepts the application's command-line
arguments plus a `BootstrapSpec`:

| Field | Meaning | Default |
|---|---|---|
| `app` | Application name used in reports | required |
| `entrypoint` | First-run script relaunched under the chosen interpreter | `first_run.py` |
| `env_var` | Environment variable set to the chosen interpreter for the exec handoff and the in-process continuation. A wrapper may branch on it and skip `bootstrap()` after the handoff | `MCP_BOOTSTRAP_INTERPRETER` |
| `package_main` | In-process continuation when already on a good interpreter. Required when the entry point calls `bootstrap()` unconditionally: a missing continuation is an error (`missing_continuation`), never a silent re-exec | `None` |
| `required` | Minimum final interpreter version | `(3, 14, 0)` |
| `pin` | Plain final interpreter version (`X[.Y[.Z]]`) installed after consent; must be at or above `required` | `3.15.2` |
| `install_args` | Arguments to `uv pip install`; path-like entries must not be absolute, Windows-rooted, or contain `..`, including attached short values (`-t/tmp/x`); `--target`, `--prefix`, `--root`, and `--python` (and short forms) are reserved | `("-e", ".")` |
| `verify_import` | Module imported, in isolated mode, to verify the install | `None` |
| `card` | Consent text returned when a download would be needed; the default names `spec.pin` | built-in card |
| `repair_card` | Consent text returned when an existing venv needs the app/MCP reinstalled | built-in repair card |

Bootstrap flags are reserved and removed before the application sees its
arguments:

- `--python PATH` — use and check a named interpreter. `--python=PATH` is also
  accepted; an empty value or a following flag is a usage error.
- `--install-python` — consent to provision the pinned interpreter.
- `--` — stop bootstrap parsing; everything after it belongs to the app.

`required` is a final-release floor: pre-release versions (`rc`, `a`, `b`,
`dev`) do not satisfy it. A spec whose `pin` is below `required` is rejected
when it is built, before any download. The chosen interpreter is exported in
`spec.env_var` for the exec handoff and for the in-process continuation.

`pin` is stricter than the version probe parser: it must be a plain
`X[.Y[.Z]]` string that `uv python install` can use. `.post` and `+local`
strings are parser-only for probes and are rejected as pins.

## Selection order

1. `--python PATH`, after probing it.
2. The currently running interpreter, when it meets the floor.
3. A project-local `.venv` that meets the floor and passes `verify_import`, when
   configured.
4. The consent card, with no install and no write.

The Python-download consent card is step 4. If a `.venv` meets the floor but
the `verify_import` check fails, bootstrap returns `needs_install` and asks for
`--install-python` before running the installer.

`verify_import` runs as `python -I -P -c "import ..."`. Only the target
interpreter's own site-packages can satisfy it: the project cwd, the script
directory, `PYTHONPATH`, and user site-packages are not on `sys.path`. A flat
package at the project root therefore cannot hide a missing install.

## Provisioning sequence

After explicit consent:

1. `uv python install <pin>` with `UV_PYTHON_INSTALL_DIR` set to the
   project-local `.uv-python` and `UV_PYTHON_PREFERENCE=only-managed`.
2. Move an existing wrong-version `.venv` to `.venv.previous`.
3. `uv venv .venv --python <pin> --seed`.
4. `uv pip install <install_args> --python <venv python>`.
5. Verify the interpreter version and, when configured, `verify_import`.
6. Write `.python-version` to `spec.pin`, but only when step 1 ran in this
   call (that is, when this run installed the pinned interpreter).
7. Exec the entrypoint under the chosen interpreter.

If a supported `.venv` already exists and only the app/MCP is missing, steps
1–3 are skipped. The repair installs into that venv and does not download
Python. Because this run did not install the pin, step 6 is skipped too: the
existing pin file is left exactly as it was (including when it is absent).

## Results and exit codes

| Code | Reason | Meaning |
|---|---|---|
| `0` | — | Handoff or in-process continuation succeeded |
| `2` | `python_flag_missing` | `--python` had no value |
| `3` | `python_too_old` | No usable interpreter and no consent |
| `4` | `needs_uv` | Consent was given, but uv is not installed; `tip` carries the official install instructions |
| `5` | `provision_failed`, `venv_locked`, `pin_write_failed` | Provisioning, verification, or pin write failed |
| `6` | `needs_install` | Existing venv is missing the app/MCP; consent is needed to repair it |
| `7` | `missing_continuation` | Re-entry with no continuation: `env_var` already names a usable interpreter and no `package_main`/`main_fn` is configured. Nothing is exec'd or downloaded |

JSON reports go to stdout. Subprocess output is captured, truncated, and
redacted; the report's `steps` carry the redacted command, return code, and
stderr. Reports include `app` plus the keys used by consumers: `ok`,
`installed`, `reason`, `found`, `required`, `pin`, `needs_consent`, `card`,
`next`, `tip`, `override`, `steps`, `interpreter`, `python_version`, and
`ran_install`.

## Non-negotiable safety properties

- Version probes and the isolated import check may run before consent. No
  install, download, or provisioning subprocess starts without explicit
  consent.
- No automatic `curl | sh`.
- No `shell=True`.
- No deletion of an existing `.venv`.
- No writes to the system Python.
- The good-running path hands off to itself at most once, to record
  `spec.env_var`. A second pass that arrives with the variable already set and
  no continuation is a `missing_continuation` report (exit `7`), never a loop.
- `root` is the trust boundary: it is the working directory for every step,
  and the consumer supplies it as its own project directory.
- Bootstrap paths and path-like `install_args` are project-local: absolute,
  Windows-rooted, and `..` values are rejected, whether they are separate
  arguments, embedded in a long flag, or attached to a short flag
  (`-t/tmp/x`). Venv-redirecting flags (`--target`, `--prefix`, `--root`,
  `--python` and short forms) are rejected.
- Path checks are lexical: they do not resolve symlinks. A symlink inside the
  project can still point outside; the consumer owns that boundary.
- Concurrent first runs against one project are not supported. There is no
  lock around the `.venv` move or the provisioning steps; run one at a time.
- The import check is isolated (`-I -P`), so the cwd cannot satisfy it.
- `tip` is human guidance only. It is never executed.
- Command arguments and captured error text are redacted for credential-shaped
  values (URL userinfo on any scheme, key/value pairs, Bearer headers) before
  they enter a report.
