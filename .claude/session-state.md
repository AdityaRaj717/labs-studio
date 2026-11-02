# Session state

**Goal:** Labs Studio as agent-controlled Flow MCP; every task proven on the real Flow page. Afterward owner gives a full UI/UX revamp brief.
**Plans:** docs/superpowers/plans/2026-11-02-flow-agent-control.md, 2026-11-02-youtube-production.md. Ledger .superpowers/sdd/2026-11-02-flow-agent-control/progress.md.
**Run:** Chrome port 9333. FLOW_DATA_DIR=D:\glabs_web\flow-mcp. Harness tools/flow_spike (win_driver.py + wcmd.sh for the real window, out/ is gitignored). Audio env names are FISH_API_KEY, STABILITY_API_KEY; load scratchpad audio.env into the process that starts the engine, never print. Owner wants speed: 30-45 min target. Do not reinstall gitleaks or osv-scanner (global rule).
**Done:** last_frame, window checks, Y8 (docs/production-live-acceptance.md), open live items, docs and CI written, tests/evals harness, 14 non-live evals scored (all met their must/never; e3 and m4 blocked by the classifier, y5 removed: agents may not start spending tools).
**Uncommitted:** docs, CI, tests/evals, tests/live/run_acceptance.mjs, tools.js descriptions, picker fix in src/flow/contract.js and ingredients.js. Run trail check, commit.
**Task 19 open:** accept.jsonl first pass 44/13; rerun with fixes in tools/flow_spike/out/accept3.log. Known: 7.6 delete "still listed" not diagnosed. Create-character from image with auto_confirm false seems to leave "Untitled character" in the project: check. Write docs/flow-live-acceptance.md from accept*.jsonl.
**Next:** BLOCKED: Flow WAF_BLOCK; no live work until owner says. Then rerun accept --only 10,11,13,18,19 and 3 live evals, check picker.search is not on the project page. Not merged.
**Not forceable live:** quote drift, quota stop. Open decisions: stitch_video 280s cap; amber review bar vs R1; flow_list_assets omits audio.
