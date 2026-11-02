# Labs Studio

PySide6 desktop app (Python) plus a bundled Node engine and MCP server for Google Flow (`mcp/google-flow/`). Vocabulary: `GLOSSARY.md`. Decision: `docs/adr/0001-flow-engine.md`. Current work: `.claude/session-state.md`.

## Commands (cmd.exe, repo root)
- Python tests (offline): `python -m pytest`
- Node tests (offline): `cd mcp\google-flow && npm ci && npm test`
- Run the app: `python run.py`
- Help screenshots (only on UI change): `.venv\Scripts\python.exe tools\make_help_screenshots.py`

## Layout
`src/` app (gen, web, ui, projects...), `mcp/google-flow/src/` engine, shim, production, `help/en/` user guide, `docs/` specs and handoffs, `tests/` pytest, `tests/live/` live runners.

## Rules
- Live Flow is touched only through the engine's controller, never by ad hoc scripts, and only with a stated credit budget.
- New work is not tested on the fake Flow (`mcp/google-flow/test/fake-flow`); prove it on the real page.
- Never start a second engine on another data dir against the same Chrome. Agents use the app's `FLOW_DATA_DIR`.
- Never write API keys into files; keys live in Windows Credential Manager.
- Run `trail check` before every commit.
- Offline suites must stay offline: no network, no browser.
