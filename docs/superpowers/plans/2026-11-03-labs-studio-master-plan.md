# Labs Studio Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans, one session block at a time. Tasks use checkbox (`- [ ]`) syntax. Every code task is test first: write the named test, see it fail, implement, see it pass.

**Goal:** Finish everything left in Labs Studio: the Contact Sheet review fixes, truthful sync with the real Flow page, every engine capability reachable in the app, subtle motion, measured performance, the paused live work, and the final review and docs.

**Architecture:** One engine stays the owner of Chrome, queue, ledger and files (ADR 0001). The app gains one truth layer (`src/gen/progress.py`, stage and timestamps from the engine) and one motion layer (`src/ui/motion.py`), then capability controls built on both. Live Flow work is a separate gated track.

**Tech Stack:** Python, PySide6 (Qt 6.12 Widgets, QSS, QPainter), pytest. Node engine and MCP shim (`node --test`), FFmpeg.

**Spec:** `.claude/session-state.md`, `PRODUCT.md`, `docs/adr/0001-flow-engine.md`, `docs/superpowers/specs/2026-11-02-youtube-production-design.md`. Evidence behind this plan: `capability-audit.md` and `unfinished-plan-tasks.md` in `C:\Users\ankit\AppData\Roaming\Claude\side-session-notes\local_63929795-1d17-4264-984e-ac678acc2fa6\` (S1-1 copies both into `docs/audits/`).

**Status when written (2026-11-03):** 312 Python tests passed in 26.7 s with no hang and no teardown error shown. Nothing was built, committed or run on live Flow by this plan.

## Global Constraints

- Live Flow only through the engine's controller, with a stated credit budget, and none until the owner says the block is cleared. Every live step is tagged **LIVE** and asks for its budget first.
- No retry loop, solver, stealth or second engine against Flow's checks (ADR 0001 rule 5). `FLOW_DATA_DIR=D:\glabs_web\flow-mcp`, Chrome port 9333.
- New work is proven on the real page, not the fake Flow. Offline code is tested on recorded data and reported as "not yet proven live" until an L task proves it.
- Offline suites stay offline. Keys stay in Windows Credential Manager. UI text goes through `src/languages/en.py`.
- Run `trail check` before every commit. Never stage the owner's `mcp/google-flow/README.md`. Commit only after the owner approves S0 Q2.
- Direction contract holds: black frames on neutral grey, red marker for decisions, amber for live only, rose plus hatch for failed. Sizes 11, 13, 20. Radii 2 px. No pills, cards or glow.
- Show real values only. Never draw a percent Flow did not report. Never count local time as engine time.
- 300k context per session. Update `.claude/session-state.md` at the end of each session and start the next one fresh.
- Delegation: `executor` for scoped multi-edit tasks, `sonnet-worker` for tests and docs, `haiku-worker` for mechanics. Design, unexplained bugs, spend logic and final review stay with the main agent, which reads every worker diff.
- End every session with `/code-review` at medium, `superpowers:verification-before-completion`, both offline suites, and a state file update.

## Review Focus

Each line has its test in the owning task.

1. The engine restarts or the app reopens mid-run: clocks come back from engine timestamps, not zero, and no frame stays amber forever (S2-3 `test_clock_survives_app_restart`, `test_reset_event_rebuilds_rows`).
2. A batch of 2000 rows where some files were deleted or are still being written: scrolling never blocks and a missing file shows a blank frame (S6-2 `test_missing_file_paints_blank`, `test_paint_never_decodes`).
3. Start with a mixed batch: agent rows, an impossible model and duration, images at 0 credits, videos at real cost (S1-2 `test_start_confirm_counts_only_own_pending`, `test_impossible_mix_stops_before_start`).
4. Animations interrupted: Inspector toggled fast, page changed mid-fade, theme switched, window closed (S7-2 `test_interrupted_crossfade_leaves_no_overlay`, S7-3 `test_rapid_toggle_ends_in_requested_state`).
5. Window moved between 100% and 150% monitors, and resized to 900x600 (S6-2 `test_dpr_change_refetches_thumbs`, S9-1 captures).

---

## Execution order

| Block | Content | Needs | Live | Est. context |
|---|---|---|---|---|
| S0 | Owner answers | none | no | none |
| S1 | Checkpoint, review fixes (a)-(l), test debts | S0 | no | 180k |
| S2 | Truth layer: stages, clocks, real progress, WAF matcher | S1 | no, L3 proves it | 170k |
| S3 | Spend and run control | S2 | no, L3 proves it | 150k |
| S4 | Takes, shots, Frames | S2 | no, L5 proves it | 170k |
| S5 | Productions from the app, assembly, audio, assets, projects | S3, S4 | no, L5 proves it | 200k |
| S6 | Optimization with measured targets | S1 (can run after S4) | no | 130k |
| S7 | Motion | S5, S6 | no | 170k |
| S8 | Plan leftovers on paper and engine tests | S1 (safe to run beside S4 to S6, it touches docs and tests only) | no | 110k |
| S9 | Visual QA, help, finish review, DESIGN.md, merge prep | S7, S8 | no | 180k |
| L0 to L6 | Paused Flow work | owner says cleared, S2-1 done | **yes** | 120k per run |

The L track does not hold up the blocks. If the block outlasts S9, the branch ships with a plain list of what lacks live proof.

---

## S0: Owner decisions

Answers are recorded in the state file. Questions are listed at the end of this plan.

## S1: Safe ground and the finish-review fixes

Tools: `trail` (ask, check), `ponytail` on code tasks, `superpowers:test-driven-development`, `superpowers:systematic-debugging` for S1-6, `impeccable:impeccable` polish references for S1-3 to S1-5, Context7 for Qt questions.

- [ ] **S1-1 Checkpoint.** Files: all current changes except `mcp/google-flow/README.md`; create `docs/audits/` with the two evidence files; move the QA harness into the repo as `tools/qa_shots.py`, since it lives in a dead session's scratchpad. Steps: run both suites, `trail check`, then commit in three groups: theme and kit, generator shell, pages and help. Tool: `haiku-worker` for the copy, main agent for the groups. Accept: `git status` shows only the README modified, suites green. Live: no. Needs S0 Q2.
- [ ] **S1-2 (a) Confirm before Start.** Files: `src/ui/generator/page.py` (button at :124, `start` at :771), `src/gen/provider.py`, `src/gen/web_flow_video.py`, `src/gen/web_flow_image.py`, `src/ui/generator/config_panel.py`, `src/languages/en.py`, `tests/test_contact_sheet.py`.
  - Add `Provider.estimate(jobs, options) -> Estimate(shots: int, credits: int | None, note: str)`. Video: `quote()` x count x shots. Image: 0 credits with the quota note, `capabilities.json` says `credits: 0`. Other providers: `credits=None`, text says the provider bills it.
  - The button connects to new `_confirm_start()`. `start()` stays unconfirmed because the webhook and tests call it. The palette uses `b.click`, so it is covered.
  - The text states shots, credits, retries allowed, and that the engine rereads the live quote before spending.
  - Duration choices come from the model's entry in capabilities, not the hard-coded list at `web_flow_video.py:39`. Count maximum follows the provider (4 on Flow), which removes the silent clamp at `web_flow_image.py:167`.
  - Tests: `test_start_asks_first_and_no_starts_nothing`, `test_start_confirm_counts_only_own_pending`, `test_video_confirm_states_credits`, `test_impossible_mix_stops_before_start`, `test_veo_offers_only_its_durations`.
  - Tool: `executor`, main agent reviews the spend text with `stop-slop`. Live: no.
- [ ] **S1-3 (b) Rose means failed only.** Decision: change the two tests. `test_colours_come_only_from_status_colors` and `test_a_rejected_row_uses_the_failed_colour` in `tests/test_production_rows.py:104,111` encode R1 from before the Contact Sheet. The owner's later contract says red marker is decisions and rose is failed, and a rejected take is a decision, not a failure. Keeping the old tests would make rejected look like an error. The first test's real aim, one source of colour, is kept: `allowed` becomes `STATUS_COLORS` plus `REVIEW_COLORS`.
  - Files: `prompt_model.py:37-38` (approved and rejected to `marker`), `sheet.py:443` (rejected tick to `marker`), those tests, R1 amendment in `docs/superpowers/specs/2026-11-02-youtube-production-design.md:174`.
  - Accept: `test_a_rejected_row_uses_the_marker` asserts the marker colour and `job.status is JobStatus.DONE`. Live: no. Tool: main agent. Depends on S0 Q4.
- [ ] **S1-4 Table and shell fixes (c), (d), (e), (f), (g), (i).** Tool: `executor`.
  - (c) `theme.py:398` forces text colour on selected cells, and Qt selected text ignores the model's foreground. Remove `color` from that rule and add `StatusDelegate.initStyleOption` in `prompt_table.py`, copying the foreground into `QPalette.HighlightedText`. Test `test_selected_failed_keeps_its_colour` renders the cell and counts failed-colour pixels.
  - (d) `help/button.py`: new `set_on_black(bool)` uses `frame_text` ink. `open_viewer` and `close_viewer` call it. Test asserts the icon token changes.
  - (e) `page.py` `toggle_inspector` and `_update_inspector`: after the reflow, `QTimer.singleShot(0, self._scroll_to_current)`. Test: selected row stays inside the viewport after a toggle.
  - (f) `sheet.py`: `_width` stays the slider's minimum. Add `_cell_width()` that divides the viewport width into whole columns and stretches cells to fill. Recompute in `resizeEvent`. Scrollbar policy `AlwaysOn` prevents a resize feedback loop. Test `test_cells_fill_the_row`: right gutter under one spacing at widths 900, 1280, 1920.
  - (g) `prompt_table.py:98` Output column widened to fit a 3:2 thumb. Failure text goes only in the tooltip and Take panel. `prompt_model.py:185` thumbs at device ratio, with `setDevicePixelRatio`. Test `test_output_thumb_uses_device_ratio`.
  - (i) Delete the rail tick at `sidebar.py:102-107`. `page.py:354` `RunNotice` is amber only while the run is live, else muted. Help links get an underline in `help/page.py`.
- [ ] **S1-5 Frame fixes (h), (j), (k), (l).** Tool: main agent, because the ring is the signature. `emil-design-eng` for the ring.
  - (h) `draw_hatch` alpha 46 to about 110, checked at 1920. Running frames get a 2 px amber keyline in `SheetDelegate.paint`.
  - (j) `tools/make_help_screenshots.py:537` crop fixed. H1 in the help page at 20 px Bahnschrift.
  - (k) `ring_points` gains low-frequency radius noise. New `ring_path()` is a filled, tapered outline, cached by `(seed, w, h)` so it is not rebuilt each paint. `take_panel.py` has no enable rule for `btn_retry`: add `setEnabled(any(j.status is not JobStatus.RUNNING for j in jobs))`, test `test_retry_disabled_on_running_frame`.
  - (l) Answered: `impeccable concept-seed --check-seed` reports `SEED UNKNOWN: not a seed reference`, and adds that a raw key never belongs in a brief. Remove the hex from the state file and say in DESIGN.md that the direction was the owner's pick, with no valid seed on record.
- [ ] **S1-6 Export hang in `tests/test_stitch.py::test_bgm_ducks_under_voice`.** Tool: `superpowers:systematic-debugging`, `sonnet-worker` for the repro loop. Reported site `src/editor/ffmpeg.py:364` is only the reader thread; the real waiter is the loop at :369-382, which has no time limit. Lead hypothesis, unproven: the sidechain graph stalls (the comment at :287 records the same family of stall with `asplit`). Second: stdin stays an open pipe.
  - Steps: loop the test 30 times with a per-run limit and keep `ffmpeg.log` and the command of each hung run. Reproduce the graph with ffmpeg alone. Fix the cause.
  - Also add `stall_seconds` to `run_export`: no progress line for that long kills ffmpeg and raises `ExportError`. A user export must not hang either way. Test `test_stalled_export_raises`, with a fake process.
  - Accept: 30 of 30 pass, cause written as a learning. If it cannot be reproduced in 30 runs, say so and keep the watchdog. Live: no.
- [ ] **S1-7 `RuntimeError` at test teardown.** File: `src/ui/help/button.py`. Not shown in today's run; the `try` at :44-49 may already cover it. Run the full suite 5 times with `-s` and search for it. If seen, fix by removing the filter on `parent.destroyed` and connect `destroyed` before the first event. If not seen, record that and close it. Tool: `sonnet-worker`. Accept: 5 clean runs.
- [ ] **S1-8 Learnings.** No `.trail/learnings` exists yet. Save with `graft note` or `trail note`: the failed-tile text, `--only` needing 8 and 9, and the export hang cause. Tool: `trail`.

## S2: Truth layer

Tools: `api-and-interface-design` for the event shape, `observability-and-instrumentation`, `error-handling-patterns`, Context7 for Qt. All tested on recorded data.

- [ ] **S2-1 WAF matcher (engine, offline).** Evidence checked: the saved screenshot `D:\glabs_web\flow-mcp\screenshots-debug\2026-11-02T17-47-04-050Z_job-failed.png` shows a normal project page with one failed tile saying "We noticed some unusual activity ... You have not been charged for this generation." The rule at `config/ui-contract.json:139` has `anywhere: true`, and `blocks.js:21` scans all body text. So a real Google signal on one generation became a sticky match: the tile stays in the grid and trips every later check.
  - Change: page-level scan excludes tile text (selector goes in the contract). A new-tile failure carrying this text gets code `FLOW_ACTIVITY_FLAG`, class `owner`, `creditsAtRisk: false` when the tile says not charged. It still stops the queue and hands to the owner. **No automatic retry**: the sub-audit's retry-once idea is rejected under ADR rule 5. `resume` rechecks the page before clearing the pause (`worker.js:286`).
  - Files: `flow/blocks.js`, `flow/observe.js:77`, `engine/worker.js`, `utils/errors.js`, `config/ui-contract.json`, `src/gen/web_flow_image.py` code maps, `test/guards.test.js`.
  - Tests on recorded text: `old failed tile does not block a new job`, `new failed tile stops with not-charged`, `whole page interstitial still blocks`, `resume refuses while the block shows`. Tool: main agent. Needs live proof in L1.
- [ ] **S2-2 Engine read paths.** Add `stage`, `submitted_at`, `attempt` to `itemView` (`production/orchestrator.js:52-73`). Emit `job.progress` with the running-tile count from `observe.js:97`, which reports the first tile only, so the app can say "first of 4". Tool: `executor`. Tests in `test/production-state.test.js`. Live proof: L3.
- [ ] **S2-3 App truth model.** Create `src/gen/progress.py`:
  ```python
  @dataclass(frozen=True)
  class ProgressView:
      stage: str              # queued, preparing, submitted, generating, downloading, verifying, or ""
      percent: int | None     # only while source == "flow" and stage == "generating"
      elapsed_s: int | None   # from the engine's submitted_at; local clock only for non-engine providers
      tiles: int              # running tiles Flow has; 1 unless the engine says more
  def progress_view(job: Job, now: float) -> ProgressView: ...
  ```
  - `models.py`: add `stage`, `started_at`, `tiles`. Reset `progress_source` per attempt at `queue.py:196`.
  - `web_flow_image.py:102`: delete `ctx.progress(0.05)`. `report_event` keeps `event["ts"]`, and `job.transition` clears the percent so 77% is not shown as "waiting".
  - `engine_client.py:205-213` `row_state`: `queued` maps to QUEUED, not RUNNING. `run_mirror.py`: `_same` also compares stage; stop ignoring `job.progress` at :121 so agent rows get real percent. `webhook/backend.py:35`: add `progress_source` and `stage`, keep `progress`.
  - Tests: `test_percent_only_from_flow`, `test_transition_clears_stale_percent`, `test_queued_agent_job_is_not_live`, `test_clock_survives_app_restart`, `test_reset_event_rebuilds_rows`, on a fixture made from a real run's `events.jsonl` with paths scrubbed. Tool: main agent writes the type, `executor` the rest.
- [ ] **S2-4 Show it.** `sheet.py:248`: remove the 2% floor. Bar only when `percent` is not None. Otherwise rebate reads `PREPARING 0:42` and the Inspector labels it "elapsed, Flow gives no percent here". `prompt_model.py:130` Progress column: `77%` or `0:42 elapsed`. Tooltip says the source. `take_panel.py`: stage, percent or elapsed, attempt, tile note. `stats_header.py`: separate Queued from Generating; the run clock is the earliest `submitted_at` for engine runs. One 1 s timer repaints only live rects. Tests `test_phase_job_draws_no_bar`, `test_queue_cell_labels_elapsed`. Tool: `executor`. Live proof: L3.
- [x] **S2-5 Engine state on the desk.** `engine_client.py`: `health() -> EngineHealth(ready, paused_reason, active, uptime_ms)` on the existing thread, every 5 s, `/health` only so it never touches the tab. `main_window.py:125` rail mark lights for any engine activity, not only the local queue. Run bar shows `Paused: <reason>` whenever the engine is paused, including agent runs. Tests `test_engine_pause_shows_for_agent_run`, `test_health_failure_shows_engine_down`, `test_rail_lights_for_agent_run`. Tool: `executor`.

## S3: Spend and run control

Tools: `error-handling-patterns`, `impeccable:impeccable` (harden), `stop-slop` on dialog copy. Principles 2 and 5 of `PRODUCT.md` apply to every button.

- [x] **S3-1 Credit meter.** `flow_mcp.py:245` status called on a worker thread, idle only, since it refuses while a job holds the tab. New widget `CreditMeter` in `src/ui/generator/credit_meter.py`, in the run bar: Flow's balance with its age, month spend, today's image quota left by model. Engine tallies are labelled as the engine's own, since hand use in Flow is not counted. Add `Resets <date>` to `flow-status.js:16` (needs L6 proof). Tests `test_meter_labels_stale_balance`, `test_meter_hidden_for_non_flow`. Tool: `executor`.
- [x] **S3-2 Batch budget.** Run-level cap field in Shot settings. App batches send it to the engine and stop on `BUDGET_EXCEEDED` with no spend. `max_generation_retries` set to 0 from the app so a failure is not retried at two layers (`config_panel.py:24` keeps the single visible control). Tests `test_batch_cap_stops_at_engine_refusal`, `test_app_sends_no_hidden_engine_retries`. Tool: main agent. Live: L3.
- [x] **S3-3 Real run control.** New in `production_actions.py`: `pause(run_id)`, `resume(run_id, accept_quote=False)`, `cancel(run_id)`, `set_budget(run_id, cap)`. Run bar buttons act on the shown run: local queue for own rows, engine for runs and Productions. `page.py:813,820`. The banner gains buttons by reason: Accept new quote (states old and new), Raise cap (asks for the number), Resume (for owner stops, says what to check in Chrome first). Cancel confirms and says credits past the credit line are spent. Per-frame cancel for own rows. Tests `test_pause_calls_engine_for_a_production`, `test_quote_drift_button_needs_confirm`, `test_resume_shows_engine_refusal`, `test_cancel_states_spent_credits`. Tool: main agent. Live: L3.
- [x] **S3-4 Connection chip.** Rail footer: account, project title, connected or not. Menu: Open in Flow (`bring_to_front`), Show Flow now (`flow_screenshot`, opens in the viewer), Run Doctor (inline pass or fail list, reuses `web_sessions_tab.py:192`), Web Sessions. Files `sidebar.py`, `main_window.py`, `session.py`. Tests `test_chip_reflects_login_state`, `test_doctor_results_inline`. Tool: `executor`. Live: L5.

## S4: Takes, shots, Frames

Tools: `domain-modeling` (keep GLOSSARY terms), `impeccable:impeccable` (layout, clarify), `break-ui` on the Take panel, `codebase-design` if `take_panel.py` needs a split.

- [x] **S4-1 Keep takes.** `models.py` adds `takes: list[Take]`; `run_mirror.py:71-75` keeps `takes[]` instead of dropping it. Test `test_item_fields_keep_all_takes`.
- [x] **S4-2 Take strip and compare.** `take_panel.py`: strip T1..Tn under the preview, each with prompt used, references used, quoted credits, verdict, actor, time. `viewer.py`: step through takes and a two-up compare. Approve an older take through `flow_production_review` with its number, plus an optional note. Frame rebate gets a take badge. Tests `test_older_take_can_be_approved`, `test_compare_shows_two_takes`, `test_note_is_sent`. Tool: `executor`, main agent checks the layout at 900 and 1920.
- [x] **S4-3 Stale and stages.** Stale becomes a frame badge and a filter (`FILTERS` in `sheet.py:269`). Production sheets group by stage with thin section marks. Tests `test_stale_filter`, `test_stages_are_grouped`. Tool: `executor`.
- [x] **S4-4 Frames and chaining.** `Job.start_frame`, `Job.end_frame`; `web_flow_video.py:52` passes them. Take panel and menu: Animate from this still, Use last frame as next start (`last_frame`). Frames toggle with two slots in Shot settings. Provider error when combined with ingredients, if the engine refuses. Tests `test_animate_from_still_sets_start_frame`, `test_last_frame_chains_next_row`. Tool: `executor`. Live: L5. Done: "last frame" is taken with local FFmpeg (same command as the engine's `last_frame`, free), since app rows have no engine run id. Live: L5.
- [x] **S4-5 Per-shot settings.** Shot settings apply per selected frame, falling back to page defaults: model, ratio, count, duration, resolution. Confirm text from S1-2 sums per shot. Tests `test_shot_override_changes_estimate`, `test_override_survives_project_reload`. Tool: main agent, since it touches spend. Done: the per-shot controls sit in the Take panel ("This shot"), not in the Shot settings tab, which stays the page default.
- [x] **S4-6 Extend and Edit a take.** Video menu: Extend (`extend_from`, Veo Lite only per findings) and Edit (`edit_from`, 20 credits measured). Each shows its cost first. Tests `test_extend_only_offered_for_supported_model`, `test_edit_states_cost`. Tool: `executor`. Live: L5, since Extend's completion marker was only partly observed. Done: the source is the clip's `flowClipUrl`, now kept on the row; rows made before this have none and the menu says so. Live: L5.

## S5: Productions, assembly, audio, assets, projects

Tools: `spec-driven-development` (short spec for the Productions page, approved by the owner before S5-1), `impeccable:impeccable` (shape, then craft), `stop-slop`, `backend-reliability` for S5-3.

- [ ] **S5-1 Start a Production from the app.** New `src/ui/production/page.py`, rail entry. Pick moodboard and prompts files, `flow_production_plan` shows cast, shots, parse errors, estimate. Fields: `max_credits`, gates, `reference_mode`, `cast_confirmed`. Start confirms cost, then hands over to the sheet. `production_actions.py` adds `plan`, `start`. Tests `test_plan_errors_block_start`, `test_start_sends_cap_and_gates`, `test_start_needs_confirm`. Live: L5.
- [x] **S5-2 Runs view.** Panel from `flow_list_runs`: name, kind, N of M, credits, state, folder, jump to frames. Credit totals come from `ledger.json` through `flow_status`. Test `test_run_row_jumps_to_frames`. Done (f0cc316): Runs tab in the Inspector; engine `runView` gains kind, dir, created_at and ledger credits (`ledger.creditsFor`). Jump finds rows by output path inside the run folder; app-run rows saved elsewhere are not found, and the panel says so.
- [x] **S5-3 Stitch as a queued job.** Done 2026-11-04: `stitch_video` returns `stitch_id` at once; `flow_wait`, `flow_job_status` and `flow_job_control` cancel take `stitch_id`; stitches live in engine memory (a restart drops one, free to redo). App: Assemble (film-slate icon, tool row) joins approved clips with local FFmpeg, FFmpeg's own progress, then opens the file; voice and music not yet placed (S5-4). Decision: `stitch_video` becomes a queued engine job polled by `flow_wait`. The 280 s cap (`engine/stitch.js:13`) cancels long edits with no output, and loudness passes on real episodes will exceed it. Progress labelled `phase`. Tests in `test/stitch.test.js` `long stitch outlives the rpc limit`, `cancel removes the partial`. App: Assemble approved in the tool row, in sheet order, shows real progress and opens the file. Test `test_assemble_uses_approved_in_order`. Tool: main agent. Live: L3 19.2.
- [x] **S5-4 Audio.** Done 2026-11-04 except placement: `flow_list_assets` on a run lists `audio` with `kind`; Inspector Audio tab makes a voice line (free Fish model by default, paid models confirmed first), loads voices, estimates then confirms Stable Audio music or effects, lists the run's audio and plays a file on double-click. NOT done: placement fields feeding Assemble (voice and music are not yet mixed in by the app); voice preview plays only after making the file. Live: none run. Decision: `flow_list_assets` includes `run.audio` entries with `kind` (`rpc.js:286-291`), read-only. Test `lists voice and music of a run`. App panel: voice line with the free Fish model by default, voice list and preview (plan Phase L2), music and SFX with Stable Audio 3 estimate first. Placement fields feed S5-3 (Phase L3). Tests `test_paid_voice_model_needs_confirm`, `test_stable_needs_estimate_then_confirm`. Live: audio APIs only, L5 for Stable with its own budget.
- [ ] **S5-5 Assets and projects.** Project assets panel from `flow_list_assets`, stating the 28-tile window. Re-download from a frame with a missing file (`flow_download`). Projects page: Open in Flow, list Flow projects and bind one. Delete stays agent-only with typed confirmation in the shim. Tests `test_redownload_restores_missing_file`, `test_listing_states_window`. Tool: `executor`.
- [ ] **S5-6 Parity gaps from L2.** After the survey, add what the owner chose in Q6. Each needs a contract entry, an engine driver, and live proof. If L2 has not run, record this as open. Live: yes.

### Capability table

Status today, from the audit (engine entries and file lines in `docs/audits/capability-audit.md`). "Keep" means no new control is needed.

| # | Capability | Today | Plan |
|---|---|---|---|
| A1 | Launch, attach, account | Settings only | S3-4 |
| A2 | Disconnect | Missing | Keep agent-only, low value |
| A3 | Bring tab to front | Auto only | S3-4 |
| A4 | Status, balance, quota | Client, no UI | S3-1 |
| A5 | Doctor | Report file | S3-4 |
| A6 | Screenshot of Flow | Inside report | S3-4 |
| A7 | Engine health, pause reason | Missing | S2-5 |
| A8 | Capabilities | Partial, wrong durations, count clamp | S1-2 |
| A9 | Pacing, daily cap | Full | Keep, show on chip |
| A10 | Image job | Full, hidden double retry | S3-2 |
| A11 | Video job | No batch total or cap | S1-2, S3-2 |
| A12 | Start and end frames | Missing | S4-4 |
| A13 | Extend, Edit | Missing | S4-6 |
| A14 | Estimate | Missing | S1-2 from the table, `flow_estimate` for Productions in S5-1 |
| A15 | Dry run | Not applicable | Used by S5-1 |
| A16 | Reference images | Full, limit not shown | S4-5 note |
| A17 | Characters and scenes as ingredients | Full | Keep |
| A18 | Idempotency key | Full, invisible | Keep |
| A19 | Batch with `stop_on` | Missing | S3-2 sends run cap; `stop_on` kept for agents |
| A20 | Job status detail | Partial | S2-3, S2-4 |
| A21 | Wait | Full | Keep |
| A22 | Run list | Rows only | S5-2 |
| A23 | Cancel | Whole queue only | S3-3 |
| A24 | Pause, resume | Local only, label misleads | S3-3 |
| A25 | Retry failed | Works by new job | Keep |
| A26 | Raise cap | Inside one dialog | S3-3 |
| A27 | Accept quote drift | Missing | S3-3 |
| A28, A29 | Plan and start a Production | Missing | S5-1 |
| A30 | Production status | One text line | S3-3, S5-2 |
| A31 | Items | Full, ungrouped | S4-3 |
| A32 | Take history | Fetched then dropped | S4-1, S4-2 |
| A33 | Approve, reject | Full, no note | S4-2 |
| A34 | Regenerate | Full | Keep |
| A35 | Production pause, resume, cancel | Missing | S3-3 |
| A36 | Production retry failed | Equivalent | Keep |
| A37 | Stale items | Tooltip | S4-3 |
| A38 | Reuse approved item | Missing | S5-1 |
| A39 | Month, balance, quota | Missing | S3-1 |
| A40 | Credits per take | Dropped | S4-2 |
| A41 | List assets | Missing | S5-5 |
| A42 | Re-download | Missing | S5-5 |
| A43 | Open file or folder | Full, video external | Keep; poster frame in S6-3 |
| A44 | Last frame | Missing | S4-4 |
| A45 | Open, create project | Implicit | S5-5 |
| A46 | List projects | Missing | S5-5 |
| A47 | Rename project | Implicit | Keep |
| A48 | Delete project | Missing, deliberate | Keep agent-only |
| A49 | Create character, scene | Full, "Untitled" bug | L4 |
| A50 | Import character | Full | Keep |
| A51 | List characters | Partial | Show on Characters page in S5-5 |
| A52 | List scenes | Missing | Same place as A51 |
| A53 to A55 | Voice, voice list, music, SFX | Key only | S5-4 |
| A56 | Stitch | Missing | S5-3 |
| A57 | Secrets | Full | Keep |
| A58 | Engine shutdown | Missing, deliberate | Keep |
| A59 | Webhook API | App's own | S2-3 adds fields |

### Flow page parity

The engine cannot press buttons nobody has driven, and the docs are from 2026-11-02. The screenshot above also shows sidebar items the audit's docs do not cover (Library, Create tool, Trash), so L2 surveys the page first.

| Tier | Flow feature | Plan |
|---|---|---|
| 1, in | Kind, models, ratios, count, duration, resolution, ingredients, characters, scenes, frames, extend, edit, live quote, download size, balance, tile progress | S1, S2, S3, S4 |
| 2, proposed in | Tile Reuse prompt, Animate, Add to prompt, Move to trash; composer Stop (`project.stop` has a contract key and no driver); Download scene; 2K and 4K download where offered | S5-6 after L2 |
| 3, Open in Flow | Share, Flag output, Set cover, Favorite, tile Rename, GIF, page view settings, Tools, Library, Create tool | S3-4 button; Q6 can promote any of them |

## S6: Optimization

Tools: `performance-optimization`, `observability-and-instrumentation`, Python `cProfile` and `tracemalloc`, Context7 for Qt threads. `chrome-devtools` does not apply, this is not a browser.

Code facts behind these tasks: `frame_pixmap` (`sheet.py:34`) decodes on the UI thread inside `paint` and stats the file on every paint. The cache key includes width, so each slider step decodes again. `_thumb` (`prompt_model.py:176`) loads full images on the UI thread, with an unbounded cache keyed by path only, so a regenerated file can show its old thumb. `apply_filter` and `RunStrip` run over all rows on every `dataChanged`. `_refresh_stats` loops six times over all jobs on every job update. `ring_points` rebuilds 180 points per approved frame per paint.

| Metric, 1920x1080, 2000 rows, frame width 240, owner's machine | Target |
|---|---|
| Cold start to window shown | 1.5 s or less |
| First build of a page | 200 ms or less |
| Import 2000 rows | 500 ms or less |
| Filter change | 50 ms or less |
| Scroll | p95 frame 20 ms or less, worst 40 ms |
| Slider drag | 30 fps or better, no decode on the UI thread |
| 100 job updates per second | under 10% of the UI thread |
| Thumbnail memory | 256 MB cap by bytes |
| RSS after scrolling the whole sheet | 600 MB or less |
| 20 viewer opens and closes | RSS growth under 5% |

These are targets until S6-1 measures. If a baseline shows one is wrong, change it with the numbers and say so.

- [ ] **S6-1 Harness and baseline.** Create `tools/perf_ui.py <rows> <width> <out.json>`: synthetic local images of realistic size and format (no Flow), scripted scroll, filter, slider, event burst and viewer cycles, measuring paint intervals, durations and RSS. Commit the baseline to `docs/perf/`. Keep it out of pytest, since timing tests flake. Tool: `sonnet-worker`, main agent reads the numbers.
- [ ] **S6-2 Thumbnail service.** `src/ui/generator/thumbs.py`: `ThumbService.get(path, w, h, ratio) -> QPixmap | None` returns the cached or nearest size and queues `QThreadPool` decoding to `QImage` (never `QPixmap` off the GUI thread), with a `ready(path)` signal repainting only that frame. Width buckets of 80 px, drawn scaled during drag. Byte-capped LRU. Key has path, mtime and bucket; stat once per load and refresh on job update. Replaces `frame_pixmap` and `_thumb`. Tests `test_paint_never_decodes`, `test_missing_file_paints_blank`, `test_regenerated_file_replaces_thumb`, `test_cache_respects_byte_cap`, `test_dpr_change_refetches_thumbs`, `test_ready_repaints_one_rect`. Tool: main agent, thread boundary.
- [ ] **S6-3 Video poster.** Poster frame from the existing FFmpeg path, on the same pool, cached on disk beside the output. No decode for unseen frames. Test `test_poster_is_lazy`. Tool: `executor`.
- [ ] **S6-4 Coalesce updates.** `model.refresh_job` batches into one `dataChanged` per changed row every 100 ms. Filter recomputes changed rows only. Stats keep running counts. Ring path cached (S1-5). Tests `test_burst_of_updates_coalesces`, `test_filter_touches_changed_row_only`. Tool: `executor`.
- [ ] **S6-5 Startup and memory.** Profile with `-X importtime` and `cProfile`. Lazy imports for editor, webhook, help. Icons cached per colour and size. `tracemalloc` over viewer cycles to catch leaks. Rerun S6-1 and commit before and after. Accept: table met, or the gap reported with numbers. Tool: `sonnet-worker` to profile, main agent decides.

## S7: Motion

Contract change: the current contract allows one authored motion, the ring. **Owner's new request (2026-11-03): subtle, seamless motion everywhere it earns its place.** S7-1 records this: the ring stays the only authored moment, and all other motion serves feedback, state or continuity.

Rules taken from `emil-design-eng` and Impeccable `animate.md`, adapted to Qt:

- **Repeated keyboard actions stay instant.** Palette, Ctrl+1..9, arrow keys, and P, X, R apart from the mark being drawn. Motion on those makes the desk feel slow, which is the opposite of the request.
- Nothing blocks input: state changes at once and the overlay is mouse-transparent.
- No `QGraphicsOpacityEffect` on pages. It applies to a widget and all its children and re-renders through software, which is costly with scroll views and full frames. Use snapshot overlays: `grab()` the old state once, draw that one pixmap per frame.
- Qt QSS has no transitions, so hover and press use a pooled overlay.
- `theme.motion_enabled()` false means every duration is 0, with no animation objects made. Progress values still update.

Curves: `OUT = cubic(0.23, 1, 0.32, 1)`, `IN_OUT = cubic(0.77, 0, 0.175, 1)`, through `QEasingCurve.BezierSpline` and `addCubicBezierSegment`.

| Interaction | Treatment | ms | Curve | Not animated when |
|---|---|---|---|---|
| Page switch by rail click | Crossfade snapshot | 140 | OUT | Ctrl+1..9, palette |
| Sheet and Queue, empty and content | Crossfade snapshot | 120 | OUT | Palette |
| Filter change | Crossfade snapshot of the grid | 120 | OUT | Palette |
| Segmented control selection | Marker slides | 160 | IN_OUT | Keyboard |
| Inspector open, close | Panel snapshot slides, sheet reflows once | 200, 150 | OUT | Narrow window, palette |
| Inspector tabs | Crossfade | 120 | OUT | none |
| Viewer open, close by mouse | Frame rect grows to the viewer picture, back on close | 200, 150 | OUT | Enter, Space, Esc |
| Viewer next, previous | Instant by key; 100 ms fade by mouse button | 100 | OUT | Arrow keys |
| Hover on frame | Keyline alpha | 90 in, 140 out | OUT | While scrolling |
| Hover on button or rail row | Pooled overlay tint | 90 in, 140 out | OUT | While scrolling |
| Press | Tint on at once, release fades | 0, 90 | OUT | none |
| Frame starts running | Amber keyline fades in | 180 | OUT | none |
| Live pulse: running keyline and rail mark | One shared beat, alpha 55% to 100%, repaints only live rects | 1600 loop | sine | Window hidden or minimised |
| Picture arrives | Fade from frame black | 180 | OUT | Off screen |
| Failed | Hatch fades in | 180 | OUT | Off screen |
| Approve | Ring (signature) | 260 | IN_OUT | Off screen |
| Reject | Cross drawn, two strokes | 90 + 90 | OUT | Off screen |
| Mark removed | Fades | 120 | OUT | none |
| Progress bar | Tween between real values only, never past the latest | 240 | linear | No percent: no bar |
| Run strip tick | Colour fade on the changed tick | 180 | OUT | More than 300 rows: instant |
| Notice, banner | Fade; height changes at once | 150, 120 | OUT | none |
| Theme switch | Whole-window crossfade | 160 | OUT | none |
| Rail collapse | Crossfade snapshot | 140 | OUT | none |
| Splash to window | Window opacity | 160 | OUT | none |
| Wheel scroll, notched wheel | Retargeting tween of the bar | 120 | OUT | Touchpad pixel deltas pass straight |
| Tooltip | `UI_FadeTooltip` after Qt's delay, instant on neighbours if Qt allows | Qt | Qt | none |
| Frame size slider | Live reflow, nearest thumb, no tween | none | none | always |
| Palette, counters, table rows, menus | No animation | none | none | always |

- [ ] **S7-1 Motion module and contract.** Create `src/ui/motion.py`. Durations as named constants, curves `OUT`, `IN_OUT`, and:
  ```python
  def enabled() -> bool
  def animate(owner, key, start, end, ms, curve, on_value, on_done=None) -> None  # same key retargets from the current value
  def crossfade(host: QWidget, change: Callable[[], None], ms: int) -> None       # snapshot, change now, fade overlay
  def slide(host: QWidget, panel: QWidget, opening: bool) -> None
  class Beat(QObject): value: float; changed = Signal()  # shared by all live marks; stops when nothing is live or the window is hidden
  ```
  Tests `test_motion_off_starts_no_animation`, `test_same_key_retargets`, `test_beat_stops_when_hidden`. Update the contract in the state file. Tool: main agent, `emil-design-eng`, Context7.
- [ ] **S7-2 Views.** Pages, sheet and queue, filter, Inspector tabs, viewer, theme, rail, splash. `main_window.py:119,202`, `page.py:404,436,455`, `viewer.py`, `splash.py`. Input source decides instant or animated: pass `animated=False` from shortcut and palette paths. Tests `test_interrupted_crossfade_leaves_no_overlay`, `test_shortcut_page_switch_is_instant`, `test_close_during_fade_is_safe`. Tool: `executor`, main agent watches it run.
- [ ] **S7-3 Controls.** `kit.py`: Segmented marker; `HoverTint` pooled overlay with two instances, applied by a tree walk beside `repolish_tree`, per-widget filters only (no application-wide Python event filter). QSS hover and pressed rules removed where the tint replaces them (29 `QPushButton`, 2 `QToolButton` sites). Inspector slide. Wheel scroller. Tests `test_rapid_toggle_ends_in_requested_state`, `test_tint_pool_has_two`, `test_disabled_button_gets_no_tint`. Fallback: if tint fails the frame budget or looks muddy on the primary button, keep QSS instant hover for that class and report it. Tool: main agent for the tint, `executor` for the rest.
- [ ] **S7-4 Frames and progress.** `sheet.py`: per-frame animation map, generalising `_rings` and `_animations`, each updating `view.update(visualRect(index))` only, not the viewport as `:369` does today. Off-screen frames skip. Cap of 12 active. Tests `test_frame_animation_repaints_own_rect`, `test_progress_tween_never_passes_real_value`, `test_more_than_cap_snaps`. Tool: main agent, `transitions-polish` values as a cross-check.
- [ ] **S7-5 Check.** Extend `tools/perf_ui.py` with a run per table row on the 2000-row sheet. Accept: p95 frame interval 20 ms or less, worst 40 ms, no rise over S6 baselines when idle (idle CPU near zero when nothing is live). View each at 2x to 5x duration through `LABS_MOTION_SCALE`, a dev-only env var. Owner runs `/review-animations`. Tool: `sonnet-worker` to measure, main agent judges feel.

## S8: Plan leftovers on paper and in engine tests

Tools: `domain-modeling` (ADR, glossary), `sonnet-worker`, `/security-review`. Local scanners were removed at the owner's request, so Task 20's gitleaks and osv-scanner step is replaced by native `/security-review`.

- [ ] **S8-1** Write `docs/adr/0002-production-review-state.md` (one writer, `production.json` is review truth, agents never self-approve). Add ADR 0003 for R1's amendment and the WAF split. Complete `GLOSSARY.md` with the YouTube terms.
- [ ] **S8-2** `tests/evals/prompts.json` to about 15 prompts, adding T-17 and "continue yesterday's run" with scoring. Offline scoring runs in `score.mjs`.
- [ ] **S8-3** `help/en/mcp-agents.md`: configs for Claude Code, Desktop, Cursor and Codex, the prompt-file format, the recovery guide. Check Y9's doc requirement; a search for the format found nothing.
- [ ] **S8-4** `docs/AGENT_CONTROL_TESTING_ISSUES.md`: close #6 (fixed at `open-project.js:207-212`), #9 stays until L4. Note `stitch_video` registered early. Test that no tool returns `NOT_IMPLEMENTED`.
- [ ] **S8-5** README stale list (`flow_account_check`, `flow_queue_status`, Grid Architect, Imagen 4): only with S0 Q5's answer, since the file has the owner's edit.
- [ ] **S8-6** CI: `.github/workflows/test.yml` on `windows-latest`, offline suites, no secrets. Tool: `ci-cd-and-automation`.
- [ ] **S8-7** `PRODUCT.md`: the line "engine, queue, providers and storage do not change" is now false; amend it to allow small read paths and the listed fixes. Platform stays `desktop`. Impeccable accepts only `web`, `ios`, `android`, `adaptive` and treats this as web, but writing `web` would be false; DESIGN.md records that no detector ran on native Qt.

## S9: Visual QA, docs, finish

Tools: `impeccable:impeccable` (lead, critique and polish), `design-floor` as a manual checklist, `break-ui`, `accessibility` as a review aid, `stop-slop` on user text, `impeccable:impeccable-finish-reviewer`, `impeccable:impeccable-documenter`, `code-review-and-quality`, `superpowers:finishing-a-development-branch`.

- [ ] **S9-1 Captures.** `tools/qa_shots.py` at dark and light, 900x600, 1280, 1920. All names the state file lists as not yet seen: light 1280 and 1920, dark 900, running, menu, light palette, log, scenes, API keys tab, collapsed rail, splash; plus every new view. Look at every image and critique it. Accept: a written list of fixes applied. Check row centring, narrow queue columns, header alignment, Characters flow line.
- [ ] **S9-2 Really running.** Capture the run bar and frames with a real queue on a local stub provider, then with an engine run in L3 if the block has cleared. The stub capture does not count as Flow proof.
- [ ] **S9-3 Real input.** Drive real drag and drop from Explorer and the native file dialogs through `anthropic-skills:computer-use` on the running app, with the owner's OK. Video opens in the default player.
- [ ] **S9-4 Worst cases.** `break-ui` on frames, Take panel, run bar, meter, Production plan: long prompts, unbroken ids, non-Latin text, emoji, 0 and 10000 rows, 99999 credits, missing fields. Report and fix.
- [ ] **S9-5 Accessibility.** Web rules do not map one to one. Check by test: every control has an accessible name, full keyboard path, focus visible, contrast by token pairs at 4.5:1 for text, state never by colour alone, motion off respected. Test `test_every_button_has_a_name` walking each page. Not a compliance claim.
- [ ] **S9-6 Fonts and provenance.** Confirm Cascadia Mono and Bahnschrift fall back cleanly. Phosphor licence (MIT) in the repo. Each shipping raster's provenance listed in DESIGN.md.
- [ ] **S9-7 Help.** Regenerate with `tools/make_help_screenshots.py`, update specs for new pages, write help for new controls. Accept: 7 or more of 7 images and every attribute path resolves.
- [ ] **S9-8 Finish review.** Spawn the finish reviewer with screenshots, contract, craft floor, the note "no detector ran, native Qt". Apply fixes, rerun until the verdict is pass. Owner optionally runs `/unslop` here; it is web-minded and user-run, so treat its output as critique.
- [ ] **S9-9 Document.** Documenter writes `DESIGN.md` and `.impeccable/design.json` from what shipped, including the motion table.
- [ ] **S9-10 Merge prep.** `/security-review`, `/code-review` on the whole branch at high, `superpowers:finishing-a-development-branch`, final report of what lacks live proof. Owner may run `/code-review ultra`. No merge without the owner's word.

## L track: Paused Flow work

Budget in **credits**, asked at each step. Balance was 792 at the last read. Expected total: about 25 credits and some image quota, cap asked 60. `MAX_DROP` in the runner is also 60.

- [ ] **L0 Owner clears it.** The owner opens Flow in Chrome on port 9333 by hand, checks for page-level warnings, disables any page-modifying extensions if Google's message applies, and says when it looks normal. This plan does not claim the cause: one flagged generation is what's proven; why Google flagged it is unknown.
- [ ] **L1 One probe. LIVE, budget ask: 0 credits, 1 image of quota.** After S2-1. One image in a new test project through the controller. Any flag stops the track and goes to the owner; no second try in that session. Also proves the new matcher, the not-charged path if it recurs, and resume's recheck.
- [ ] **L2 Page survey. LIVE, 0 credits.** `flow_doctor` and `flow_screenshot` through the engine, plus read-only menu opening where the doctor does it. Update `docs/flow-ui-findings.md`: Library, Create tool, Trash, tile menu. Feeds S5-6. No generation.
- [ ] **L3 Acceptance rerun. LIVE, budget ask: about 4 credits, cap 10.** Corrected command, because `--only 10,11,13,18,19` cannot pass alone (10.1 needs sections 8 and 9):
  ```
  set FLOW_DATA_DIR=D:\glabs_web\flow-mcp
  set FLOW_CDP_PORT=9333
  set FLOW_TEST_PROJECT=<new test project url>
  node tests\live\run_acceptance.mjs tools\flow_spike\out\accept4.jsonl --only 8,9,10,11,13,18,19
  ```
  While it runs, watch the app: stages, Flow's real percent, elapsed labels, pause, credit meter (S2, S3 proof). Record in `docs/flow-live-acceptance.md`.
- [ ] **L4 Task 19 leftovers. LIVE, 0 credits.** 7.6 still listed: the engine log shows delete `ok:true` each time (in-page link detached), so the failure is in the later list. Ranked: server lag or soft delete into Trash; SPA cache on `goto(HOME)`; test match. Run create, delete, then list at 0, 5, 15, 60 s with raw entries, plus a list after `reload` and a look at Trash, through a controller-run test section. `superpowers:systematic-debugging`; failing test first; fix the tool or the test by evidence. Same session: "Untitled character" and issue #9.
- [ ] **L5 Proof of new controls. LIVE, budget ask: about 15 credits, cap 25.** Omni 360p 4 s with Frames, last-frame chain, Extend on Veo Lite if chosen (10), Edit only if the owner adds 20. Pause, resume and cancel on a Production. Assemble. Stable SFX: separate ask, 8 Stability credits. Report any failure plainly; a failure reopens the S task.
- [ ] **L6 Evals. LIVE, budget ask: 0 credits, image quota including Pro for `live2-pro`; Y9's two live evals at most 25.** `live1-image`, `live2-pro`, `live3-continue` by a fresh `sonnet-worker` through `tests/evals/mcpcall.mjs`, scored by `score.mjs`. No `live*.jsonl` exists, so none has run. Also read `Resets <date>`. Quote drift and Google's quota stop stay unprovable on demand; say so.

## Skills and tools, plainly

| Tool | Status |
|---|---|
| `superpowers:writing-plans`, `emil-design-eng`, Context7 (Qt), Impeccable `animate.md`, `init.md` and CLI seed check, `transitions-polish` values | **Used to write this plan** |
| `impeccable:impeccable` (lead), finish reviewer, documenter, `design-floor`, `break-ui`, `accessibility`, `stop-slop`, `performance-optimization`, `observability-and-instrumentation`, `error-handling-patterns`, `api-and-interface-design`, `backend-reliability`, `spec-driven-development`, `domain-modeling`, `codebase-design`, TDD, debugging, verification, `code-review-and-quality`, `ponytail`, `trail`, `ci-cd-and-automation`, `computer-use` | Assigned above, not run yet |
| `codebase-memory-mcp`, `trail ask` | Use for blast radius before S2-3 and S7-3. `graft` is not on the Git Bash PATH here; `trail` is |
| `/unslop`, `/review-animations`, `/code-review ultra` | Owner-run only, at S9-8, S7-5, S9-10 |
| `design-taste-frontend` | Installed, the owner's "taste skill". For websites and marketing pages only, so it is not applied to native Qt |
| `design-floor`, `accessibility` | Written for web. Used as manual checklists; their detectors do not run on Qt |
| GSAP skills, `vercel-react-*`, `vercel-composition-patterns`, Three.js skills, `scroll-craft`, shadcn, Motion | Cannot run in Qt. Not used |
| `chrome-devtools`, `playwright-cli`, `web-qa`, built-in browser | Web only. Also barred from Flow by the controller rule |
| Figma, Refero | Refero reference search was partly done earlier. No Figma file exists. Not needed |
| UI UX Pro Max | **Not installed.** Nothing by that name in the session's skill listing, `~/.claude/skills` or a plugin catalog search. Impeccable holds that job. The catalog's Anthropic "Design" plugin (critique, accessibility, UX copy) is not installed and would overlap, so it is not proposed |
| `anatomy`, `diagram-design`, `dataviz` | Not needed, unless S3-1's meter grows a chart |

---

## Questions only the owner can answer

Q1. Approve this plan, and which way to run it: subagent-driven (recommended) or native?

Q2. Commit and push: may S1-1 commit the Contact Sheet work now, split into three groups? Also, `feat/flow-agent-control` (47 commits ahead of `main`) and this branch exist only on this disk; only `main` is on `origin`. Recommended: push both to `origin` now, base stays stacked, PRs in order. Which remote, `origin` or `upstream`?

Q3. Flow block: tell me when Flow looks normal by hand. Then approve credits per step: L1 0, L2 0, L3 up to 10, L4 0, L5 up to 25, L6 up to 25. Cap 60 in total. Stable SFX is separate: 8 Stability credits, yes or no?

Q4. Colours: approved and rejected in the marker red, rose for failed only, amber for live only, replacing R1's literal colours. Recommended yes.

Q5. `mcp/google-flow/README.md`: it holds your uncommitted edit and lists tools that no longer exist. Should I fix those lines on top of your edit, or leave the file?

Q6. "Every Flow button": tier 1 and 2 of the parity table get real controls, tier 3 gets Open in Flow. Which tier 3 items do you want promoted? Each needs an engine driver and live proof.

Q7. Motion: repeated keyboard actions stay instant, as above, so the desk never feels slow, and all else animates. Recommended yes.

Q8. Local Small audio models (Task 17) stay skipped. Recommended yes.
