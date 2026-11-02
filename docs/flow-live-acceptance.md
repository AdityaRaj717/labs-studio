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
