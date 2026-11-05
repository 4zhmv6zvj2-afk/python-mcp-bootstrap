# Python version policy

## Three numbers, never confused

- Floor: 3.12.0 (minor line). Metadata: `requires-python = ">=3.12"`.
  Code: `sys.version_info >= (3, 12)`. A patch is never a floor.
- CI lines: 3.12 (floor), 3.13, 3.14, 3.15. The runner resolves the latest
  patch in each line (`check-latest: true`) and the job prints it (`python -VV`).
- Product provisioning pin: 3.15.2 (deliberate, not "latest").

## Repos

All Python repos: `grokbot-essay-writer`, `python-mcp-bootstrap`,
`crypto-snapshot`, `wechat-reply`, and `1231FS-home`'s Python engine. Committed
`.python-version` files name the line `3.15`; product installs write the exact
`PIN` 3.15.2.

## Bump rule

Line-level only: add the next line when it ships; drop a line at EOL; change the
floor only as a deliberate policy change. Never hand-bump patch numbers.

## Vendoring

Consumers vendor `python-mcp-bootstrap` `core.py` with `VENDOR.json` (`name`,
`version`, `tag`, `commit`, `source`, `file`, `sha256`). No local patches.
Update via the bootstrap's `scripts/vendor.py` at a released tag.
