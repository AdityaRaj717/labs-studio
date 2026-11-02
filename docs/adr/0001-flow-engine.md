# ADR 0001: One local engine owns Chrome, the queue and the files

Status: accepted, 2026-11-02. Full reasoning: `docs/superpowers/specs/2026-11-02-flow-agent-control-design.md` (calls C1 to C12).

## Context

Two programs (the Labs Studio app and an agent's MCP server) used to drive the same Flow tab. Two owners of one tab caused hijacked generations, lost job results on restart, and pacing and daily caps that agents skipped.

## Decision

1. One local **engine** (Node, `mcp/google-flow/src/engine/`) owns Chrome, the Flow tab, the job queue, the ledger and every file written. It listens on 127.0.0.1 and records its port and token in `engine.json` inside `FLOW_DATA_DIR`.
2. The MCP server is a thin **shim** (`src/shim/`): it defines tools and forwards calls to the engine, starting it if none is alive. It holds no browser code.
3. The app and every agent are clients of the same engine. They share it only when they use the same `FLOW_DATA_DIR`. The app uses `<diag_dir parent>\flow-mcp` (default `D:\glabs_web\flow-mcp`).
4. The page is driven through Flow's direct composer; Flow's internal `batchexecute` is never called (C3, C10).
5. A CAPTCHA, a "verify it's you" page or a Google limit stops the work and hands over to the owner. No retry loop, no solver (C9).
6. Money safety lives in the engine: the quoted credits are read before Start, a quote above `max_credits` stops with no spend, and the ledger records what was submitted. A submitted job is never re-run except by an explicit retry.
7. Testing is on the real page only. The fake Flow is kept for old tests; nothing new is proven on it.

## Consequences

- Agents get pacing, caps, the ledger and recovery for free; the app shows the same queue truthfully.
- Killing the engine is survivable: state is on disk, and a restart does not spend twice.
- A second data dir means a second engine and a second tab; do not do that on one Chrome.
- Live testing spends the owner's credits, so it is run only under a stated budget.
