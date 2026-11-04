# Flow live acceptance (Task 19), 2026-11-02

Runner: `tests/live/run_acceptance.mjs` on real Flow. First pass 44 of 57, then failed sections rerun after fixes.

**INCOMPLETE. Stopped on `WAF_BLOCK` ("unusual activity") from Flow during the third pass, at test 10.1. Live work stopped at once.**

| Sections | Result |
|---|---|
| 1-6, 15, 16 | PASS |
| 7 projects | PASS. 7.6 first read "still listed"; a later list showed none, so the listing lags. Not rerun as a test |
| 8, 9 characters, scenes | PASS after test fix |
| 12 audio | PASS, Fish free voice 42 KB, Stable estimate only |
| 14 import | PASS on second pass |
| 10.1 two named ingredients | NOT PROVEN. Picker fix made, then the block arrived |
| 11.2, 13.2, 18.2, 19.1, 19.2 | NOT RUN to a result, queue held by the block. Video generation and last_frame were proven separately the same day |

Credits in this task: 800 to 792.

Open: creating a character from an image with auto_confirm false appears to leave an "Untitled character" in the project (not diagnosed).

## L track rerun, 2026-11-04 (engine controller via the MCP shim, Chrome 9333, one engine)

Run log: `tools/flow_spike/out/ltrack-2026-11-04.log`, results `tools/flow_spike/out/accept4.jsonl`. Balance read 838 at start (was 792 on 11-02), 834 after.

| Step | Budget stated | Result |
|---|---|---|
| L0 | 0 | Owner had said the block was lifted. The engine launched Chrome itself; no warning on the page (screenshot `2026-11-04T07-33-37-622Z_l2-survey.png`) |
| L1 | 0 credits, 1 image | The held 11-02 job (paper boat, Omni 360p 4 s) ran on relaunch: done, 640x360 4 s MP4, sha256 checked, no flag. Then 3 more held jobs drained. Progress was `source: phase` only: Flow gave no percent |
| L2 | 0 | `flow_doctor` 15 of 15 found, signed in. Flow's left rail now shows Library (+), Tools, Create tool, Trash |
| L3 | ~4, cap 10 | `--only 8,9,10,11,13,18,19`: all PASS, 10.1 included (two named ingredients, the step the WAF block stopped). 19.2 failed on its pre-S5-3 contract; runner fixed (ac1a894) and rerun alone: PASS, 2264781 B MP4. Spent 4 credits |

App defect seen live and fixed: the rail chip said "Flow engine off" while a job held the tab (6dac140).

### L5 in the app (2026-11-04, computer use, 1280 only)
- Pass: Start confirm with cost, Pause/Resume, Stop, Frames + last-frame chain (engine spec mode=frames), Edit this clip (20 credits, via mediaId), Assemble (12.1 s film). Spend 28 credits.
- Fixed: e7dde30 (Retry after Stop, Extend/Edit source, held icon, dialog title, Take panel at 1280), dec573b (meter refresh after run, ageing label).
- Open: the Audio voice line fails silently on MISSING_API_KEY; Stable SFX, Assets, Productions, the rail chip ("account not read" on the clip edit page), screenshots at 1920, L4, L6 not done.
