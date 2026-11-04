# Example first run

This is a tiny app that uses the bootstrap the way a consumer does: it imports
the vendored core from `_vendor/`, not the repository package.

The vendored copy is generated (and gitignored), so generate it first:

```bash
python scripts/vendor.py --target examples --dest _vendor/python_mcp_bootstrap.py
python scripts/vendor.py --target examples --dest _vendor/python_mcp_bootstrap.py --check
cd examples
python first_run.py --install-python
```

The first run installs the pinned Python under `examples/.uv-python`, creates
`examples/.venv`, installs this app, verifies `example_mcp`, and re-executes
`first_run.py` under that interpreter. The second run reaches `continue_setup`.

CI runs the same vendor + check + first-run sequence on Python 3.12 with real
`uv`. See [`docs/integration.md`](../docs/integration.md) for the consumer
layout.
