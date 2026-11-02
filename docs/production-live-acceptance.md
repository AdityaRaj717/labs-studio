# Production live acceptance (Task Y8)

Run 2026-11-02 on real Flow, in the real app window, driven by `tools/flow_spike/win_driver.py` (Qt events and key events on the running app, not a human mouse; the window was minimised for part of it). Agent side: `tests/live/run_production.mjs`.

| Check | Result | Evidence |
|---|---|---|
| Stills-only `samples/zombie-bunker`, `MD_04 -> place` | PASS: 4 references, 8 stills, no video job, balance 839 flat | run 20261102-205723-y8-stills |
| Mixed `samples/zombie-bunker-animated`, cap 35 | PASS: 27 credits estimated, 27 spent, balance 839 to 812 | run 20261102-211513-y8-mixed |
| Rows and banner in the window against status | PASS: new app project per Flow project, rows and counts match at each stage | window grabs in tools/flow_spike/out/win |
| Approve (Ctrl+Return), Reject | PASS | same |
| Modify and Retry a Still | PASS: new take, no credit, other files sha256 unchanged | same |
| Modify an Animation, cost dialog | PASS: "Regenerate ANI_01 for 4 credits?", 4 spent, other files unchanged | same |
| Silence | PASS: 6 deliverables 0 audio streams, 6 `_original` 1 each | ffprobe, run folder |
| Kill engine 3 s after ANI_06 started, restart | PASS: no second spend, ledger 27 = balance 27 | same |
| Close Chrome during Retry of ANI_02 | PASS: row failed, "Chrome or the Flow tab closed while the job ran"; that attempt was still charged 4 | balance 808 to 800 across close and redo |
| Retry past the cap | PASS: dialog offers raising to 39, set_budget applied, take done | spent 39 = 839 - 800 |
| Character reference mode | PASS after fix: character created, Still generated | run 20261102-222347-open-char3 |
| Production pause, resume, cancel | PASS: paused holds the next item; cancel stops the rest | open.log |

Total: 39 credits against the 60 owner limit. Contact sheet not viewed by the owner yet.

Found and fixed: flow_doctor refused any Frames-mode composer (the Start chip picker has only Images and Uploads tabs); raising the daily cap left the queue stopped with no app control; a paused queue left the row's job queued to run later unseen; Character mode stalled for good when the tab was still held; a free-form plan shot with no kind vanished silently.

Not provable on demand: quote drift (Flow must change a price) and the Google quota stop (needs the daily limit exhausted).
