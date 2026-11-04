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

1. `--python PATH`, after probing it and, when `verify_import` is configured,
   importing the module under it. An explicit interpreter is never silently
   replaced: a failure is reported as `verify_import_failed` (exit `5`).
2. The currently running interpreter, when it meets the floor and, when
   `verify_import` is configured, can import the module. A good-enough
   interpreter that cannot import the app is treated as unusable for this
   application and selection continues.
3. A project-local `.venv` that meets the floor and passes `verify_import`, when
   configured.
4. The consent card (or the repair card), with no install and no write.

The Python-download consent card is step 4. If a `.venv` meets the floor but
the `verify_import` check fails, bootstrap returns `needs_install` and asks for
`--install-python` before running the installer. The same `needs_install` report
is returned when the running interpreter meets the floor but cannot import the
app; with consent, provisioning continues into the project-local `.venv`.

`verify_import` runs as `python -I -P -c "import ..."`. Only the target
interpreter's own site-packages can satisfy it: the project cwd, the script
directory, `PYTHONPATH`, and user site-packages are not on `sys.path`. A flat
package at the project root therefore cannot hide a missing install.

## Provisioning sequence

After explicit consent, `provision()` runs in this order:

1. Resolve `uv` (including the project-local search paths). If it is missing,
   return `needs_uv` (exit `4`) with the official install tip; uv is never
   downloaded or installed.
2. If a `.venv` exists, probe it:
   - meets the floor and passes `verify_import` (when configured) — reuse it:
     no download, no new venv, and no pin write;
   - interpreter too old, or the app/module is missing — move it aside to
     `.venv.previous[-N]` (never deleted); a lock or OS error returns
     `venv_locked` (exit `5`);
   - a non-venv `.venv` directory is moved aside as well.
3. When the venv must be (re)built, run `uv python install <pin>` and then
   `uv venv .venv --python <pin> --seed`, with `UV_PYTHON_INSTALL_DIR` set to
   the project-local `.uv-python`, `UV_PYTHON_PREFERENCE=only-managed`, and
   `UV_PYTHON_DOWNLOADS=automatic`.
4. `uv pip install <install_args> --python <venv python>`.
5. Verify with `verify_import` when configured, then probe the interpreter
   version against the floor. Either failure returns `provision_failed`
   (exit `5`).
6. Write `.python-version` with `spec.pin`, but only when step 3 ran in this
   call, that is, when this run installed the pinned interpreter.
7. Return the chosen interpreter to the caller, which execs the entrypoint (or
   continues in-process); an `OSError` during the handoff returns
   `exec_failed` (exit `8`) as a JSON report.

If a supported `.venv` already exists and only the app/MCP is missing, steps
3–4 become a repair install into that venv: no Python download. Because this
run did not install the pin, step 6 is skipped and the existing pin file is
left exactly as it was (including when it is absent).

## Results and exit codes

| Code | Reason | Meaning |
|---|---|---|
| `0` | — | Handoff or in-process continuation succeeded |
| `2` | `python_flag_missing` | `--python` had no value |
| `3` | `python_too_old` | No usable interpreter and no consent |
| `4` | `needs_uv` | Consent was given, but uv is not installed; `tip` carries the official install instructions |
| `5` | `provision_failed`, `venv_locked`, `pin_write_failed`, `verify_import_failed` | Provisioning, verification, or pin write failed; `verify_import_failed` is reported when an explicitly chosen interpreter cannot import `verify_import` |
| `6` | `needs_install` | Existing venv is missing the app/MCP; consent is needed to repair it |
| `7` | `missing_continuation` | Re-entry with no continuation: `env_var` already names a usable interpreter and no `package_main`/`main_fn` is configured. Nothing is exec'd or downloaded |
| `8` | `exec_failed` | The chosen interpreter could not be started (for example it vanished between probe and exec). A JSON report with a redacted `detail` is written; no traceback escapes |

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
