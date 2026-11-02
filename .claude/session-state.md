# Session state

**Goal:** Labs Studio as an agent-controlled Google Flow MCP (image, video, batch), YouTube production with per-item review, Fish Audio, Stable Audio 3. UI frozen except YouTube spec R1. Owner wants every Flow task and the YouTube automation proven live through the MCP.

**Spec:** docs/superpowers/specs/2026-11-02-flow-agent-control-design.md; YouTube spec beside it.
**Plan:** docs/superpowers/plans/2026-11-02-flow-agent-control.md (read Spike rulings and YouTube section); docs/superpowers/plans/2026-11-02-youtube-production.md.
**Findings:** docs/flow-ui-findings.md (including Y0).
**Ledger (authoritative, read its last 10 lines first):** .superpowers/sdd/2026-11-02-flow-agent-control/progress.md; constraints.md beside it.
**Execution:** superpowers:subagent-driven-development on feat/flow-agent-control; implementers executor, reviewers general-purpose, re-reviews may use sonnet-worker. /ponytail once per session. Controller alone touches live Flow. Each resume of an implementer is costly: small live fixes by controller with Edit, then reviewed.

**Credits:** owner lifted test caps 2026-11-02 ("i dont care how many credits"). Spend what live tests need, report totals. Balance 967 before one extend. Test project 065acc3b-852c-4cf2-84c6-80359d0543bd (y0-2026-11-02), holds Character "y0 narrator".
**Baseline:** pytest 387, npm test 197 pass at b260ac8. FFmpeg at D:\Apps\ffmpeg\ffmpeg-9.0.2-essentials_build\bin (not on PATH, by decision).
**Chrome:** start with --remote-debugging-port=9333 --user-data-dir=D:\glabs_web\chrome-profile; signed in, currently running.

**Status:** Phases 0-2, Y0, Task 9 done. Task 10 partly done and live-proven; extend, edit, first+last frames open. Not pushed. App Flow image generation broken until Task 13: do not merge before it. Owner ruling: nothing against fake Flow, real page only.

**Next action:** see the ledger's last lines: finish extend from scene 8187e58a, then edit, then Task 11.

**Open:** owner enters API keys at Tasks 15, 16. Failed-tile UI and block wording unobserved live. Video ingredient limit unknown (Y8).

**Decisions:** spec sections 2, 3; C10 direct composer; C11 local silent; C12 quote gate; referenceMode ingredient (Y0); Y0 ran after Task 8. 300k context ceiling: save, then offer a new session.
