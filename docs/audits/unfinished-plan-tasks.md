# Unfinished plan tasks inventory (read-only, 2026-11-03)

Repo D:\Prog\labs-studio-dev, branch feat/ui-contact-sheet (off feat/flow-agent-control). Sources read in full: both plans, ADR 0001, both live-acceptance docs, AGENT_CONTROL_TESTING_ISSUES.md, session-state "Paused Flow work". Verified against files, git log and the live engine log in D:\glabs_web\flow-mcp\logs\flow-2026-11-02.log plus the saved failure screenshot.
Caveats: `graft` is not on PATH in this shell, so I used grep/ls/git. I did not run any test suite, so "DONE" means code and commit exist, not that tests pass today. No browser, Chrome or Flow was touched.

## 0. Headline findings

1. The WAF_BLOCK is very probably a false positive from tile text, not a Google-wide block. The failed-job screenshot `D:\glabs_web\flow-mcp\screenshots-debug\2026-11-02T17-47-04-050Z_job-failed.png` shows a normal Flow project page with one failed tile reading "We noticed some unusual activity. Note that browser extensions that modify the page may cause issues ... You have not been charged for this generation." The rule is `WAF_BLOCK` with `"anywhere": true`, which scans the whole page body (see 2a). That failed tile stays in the project grid, so the engine keeps seeing the text. The queue paused, and `credits_at_risk: true` was set although the tile says no charge.
2. Plan says `stitch_video` stays unregistered until Phase L, but Task 18 (stitcher) and the tool are built and registered (commit 1384a9c; `shim/tools.js:203`, `engine/rpc.js:274`).
3. `docs/adr/0002-production-review-state.md` (Task 20 requirement) does not exist.
4. Evidence commit 146a8bf contains only `docs/flow-live-acceptance.md`. The 7.6 evidence is in `tools/flow_spike/out/accept.log` and `accept2.log` (+ `.jsonl`), not in that commit.

## 1. Task by task

Status key: DONE / PARTIAL / NOT DONE / BLOCKED-LIVE. Commit hashes from `git log --oneline -40`. Credits are from the plan/docs, else "unknown".

### Base plan (2026-11-02-flow-agent-control.md)

| Task | Status | Evidence | Remains | Live? | Credits |
|---|---|---|---|---|---|
| 1 Working baseline | DONE (no own commit found in the last 40; state file and `npm test` exist) | `.claude/session-state.md`, `mcp/google-flow/test/smoke.test.js` | Nothing known. Plan says `npm test` = `node --test test/*.test.js` (spike ruling) | no | 0 |
| 2 Paid spike | DONE | commits bf389b4, 8b91788, `docs/flow-ui-findings.md` | none | was live | cap 40, done |
| 3 UI contract and doctor | DONE | `config/ui-contract.json`, `src/flow/contract.js`, `src/tools/doctor.js`, `test/contract.test.js`; accept 15.1 PASS | Doctor was fixed for Frames composer (production-live-acceptance) | no | 0 |
| 4 Clear logged issues | DONE (per issue log: #1,2,3,4,5,7,8 obsolete) | `test/issues.test.js`; issue #6 and #9 still marked OPEN in `docs/AGENT_CONTROL_TESTING_ISSUES.md` | #6 delete race: deleteFromHome now waits for the link (`open-project.js:207-212`), so code is fixed, doc status stale. #9 error bubble capture: untested live | partly | 0 |
| 5 Job store, queue | DONE | `src/engine/{journal,job-store,run-folder}.js`, `test/job-store.test.js` | none | no | 0 |
| 6 Validation, capabilities | DONE | `validate.js`, `capabilities.js`, `budget.js`, `filenames.js`, tests; accept 16.x PASS | none | no | 0 |
| 7 Tab lock, pacing, blocks | DONE (commits 80795cb, a163d94) | `tab-lock.js`, `pacer.js`, `flow/blocks.js`, `ledger.js`, `test/guards.test.js` | detectBlock false-positive risk, see 2a | no | 0 |
| 8 Engine server, shim | DONE (70348e6 + 2 review-fix commits) | `engine/server.js`, `worker.js`, `shim/*` | none | no | 0 |
| 9 Image pipeline | DONE (455bba6, e0f6f7d, 2b50778) | `flow/image.js`, `observe.js`, `download.js`, `verify.js`; accept 2.x-6.x PASS | none | proven live | free quota |
| 10 Video pipeline | DONE on image-of-evidence; PARTIAL for acceptance | commits 8b91788, a3c42b7, bf389b4; video proven live separately ("Video generation and last_frame were proven separately the same day") | acceptance 11.2 and 19.1 not run to a result (WAF pause) | yes | Omni 360p 4s about 4 each |
| 11 Batch, reconcile, projects, characters | PARTIAL | commit 985f74a, 38e87c9 (edit costs 20 credits measured); accept 13.2 and 18.2 NOT RUN to result | rerun 13.2 (2 images), 18.2 (idempotent image); open: "Untitled character" left behind by create_character with auto_confirm false (undiagnosed) | yes | images: quota only; 13.2 `max_credits 1` |
| 12 Remove unrelated features | DONE | 062a8da | none | no | 0 |
| 13 App on the engine | DONE | e13 commit c7... ("Task 13: app on the engine, live sync" e7c8516); `src/web/engine_client.py`, `tests/test_engine_client.py` | none | proven live in Y8 window runs | 0 |
| 14 Agent runs in the app, video page | DONE | 4f4c424; `src/web/run_mirror.py`, `tests/test_run_mirror.py`, `tests/test_web_flow_video.py` | none | no | 0 |
| 15 Fish Audio | DONE | df12f59; accept 12.2 PASS (42 KB mp3, free model) | none | proven | 0 |
| 16 Stable Audio 3, keys | DONE except live | 9274fd9; `audio/stable.js`, `src/keys_push.py`, `tests/test_audio_keys.py`; accept 12.3 is estimate only | live 10 s SFX (8 of 25 free Stability credits) not done | audio API, not Flow | 8 Stability credits |
| 17 Local Small models | NOT DONE, optional, skipped by decision (C4) | no `tools/stable_audio/` | only if owner chooses | no | n/a |
| 18 Stitcher (Phase L1) | DONE early | 1384a9c, 7d3050f; `src/editor/stitch.py`, `src/stitch_cli.py`, `mcp/google-flow/src/engine/stitch.js`, `tests/test_stitch.py`; `stitch_video` and `last_frame` registered | acceptance 19.2 not run; plan said not registered. `test_bgm_ducks_under_voice` hangs intermittently (session-state "Test note", `src/editor/ffmpeg.py:364 pump`) | 19.2 needs a clip | 0 beyond the clip |
| 19 Guide rewrite, all live tiers | PARTIAL / BLOCKED-LIVE | c295529, 5123f58, 16cab08, 146a8bf; `docs/flow-live-acceptance.md` says INCOMPLETE; first pass 44 of 57 | sections 10, 11, 13, 18, 19 incomplete; 7.6 unexplained; guide section 7/14/17 coverage; `AGENT_CONTROL_TESTING_ISSUES.md` #6 #9 statuses; no-NOT_IMPLEMENTED test (grep `NOT_IMPLEMENTED` in tests not checked) | yes | cap 300; spent so far about 800 to 792 in this task; Y8 spent 39 |
| 20 Evals, docs, final review | PARTIAL | `tests/evals/{prompts.json (12 prompts),production_prompts.json (5),score.mjs,mcpcall.mjs,README.md}`, `GLOSSARY.md`, `CLAUDE.md`, `.github/workflows/test.yml` exist (commit 16cab08) | plan wants about 15 prompts, T-17 campaign and "continue yesterday's run" scored; 3 live evals not run; `docs/adr/0002-production-review-state.md` MISSING; GLOSSARY must contain the YouTube vocabulary (4 hits only for Take/Production/Reference Sheet, check completeness); help/mcp-agents.md configs for Claude Code, Desktop, Cursor, Codex; recovery guide; step 3 gitleaks/osv-scanner/`/security-review`/whole-branch review (note: global rule says local scanners were removed, so use native `/security-review` only); step 4 finishing-a-development-branch; CI on windows-latest | 3 evals live | see 2c |

### YouTube plan (2026-11-02-youtube-production.md)

| Task | Status | Evidence | Remains | Live? | Credits |
|---|---|---|---|---|---|
| Y0 Reference spike | DONE | 4e71405; `tools/flow_spike/out/y0/`, `config/production.json`; images and video legs recorded | none | was live | image quota; video leg <= 15 |
| Y1 Prompt files, plan | DONE | 46e05bd; `src/production/{parse,plan}.js`, `test/production-parse.test.js`, `production-plan.test.js`; `samples/zombie-bunker` | none | no | 0 |
| Y2 Production state | DONE | 8610e90; `src/production/state.js`, `test/production-state.test.js` | none | no | 0 |
| Y3 Compose, attach, silent | DONE | 24ba6c0; `compose.js`, `test/production-compose.test.js`, `production-attach` tests, `flow/silent.js` | none | no | 0 |
| Y4 Orchestrator, start, status, resume | DONE | cd3c46b, 847e10b; `orchestrator.js`, `store.js`, `test/production-run.test.js` | quote drift and Google quota stop "not provable on demand" (production-live-acceptance) | no | 0 |
| Y5 Review, regenerate, budget | DONE | 22aa31f; `test/production-review.test.js`; Y8 proved Modify/Retry/set_budget | none | proven | 0 images, 4 per animation |
| Y6 Production rows in table | DONE | a2ba04b; `tests/test_production_rows.py` | session-state 3b(b) wants rose recoloured: approved/rejected to marker in `prompt_model.py:37-38` and tests changed; this conflicts with R1 (see 2e) | no | 0 |
| Y7 Review controls | DONE | c0e1bfe; `tests/test_review_controls.py` (modified, uncommitted) | uncommitted changes on UI branch | no | 0 |
| Y8 Live acceptance | DONE | `docs/production-live-acceptance.md`: all rows PASS, 39 of 60 credits | contact sheet "not viewed by the owner yet"; quote drift and quota stop unproven | was live | 39 spent |
| Y9 Cold-agent evals, docs | PARTIAL | `tests/evals/production_prompts.json` (5 prompts), `score.mjs`; logs for y1..y6 in `tools/flow_spike/out/evals` | the "two that need it live" (<= 25 credits) not found; confirm `help/en/mcp-agents.md` documents the prompt-file format and workflow (grep for the format found nothing) | 2 live | up to 25 |
| Phase L (L1 stitcher, L2 voice, L3 assembly) | L1 DONE early; L2, L3 NOT DONE | see Task 18 | voice selection row, `preview_voice`, SFX placement, assembled-video eval | L3 maybe | unknown |

## 2. Paused live work

### 2a. WAF_BLOCK

- Detection: `mcp/google-flow/config/ui-contract.json:139` rule `{ "code": "WAF_BLOCK", "text": "unusual (traffic|activity)", "anywhere": true }`; matcher `mcp/google-flow/src/flow/blocks.js:7-25`. With `anywhere: true` it tests the regex on `notices + body` (whole `body` innerText), case-insensitive.
- Callers: `src/engine/worker.js:88` (`failureOf`, run after any job error, 5 s race via `BLOCK_CHECK_MS`), `src/flow/observe.js:77` (every poll while waiting for tiles; returns `status:'blocked'`), `src/flow/clip.js:67`.
- Behaviour on a hit: error class is `owner` (`src/utils/errors.js:60`): job goes to `needs_user`, `pause(code)` sets the in-memory `paused` reason, Chrome is brought to front (`worker.js:103-106`). Log: `Job stopped ... WAF_BLOCK ... kind owner creditsAtRisk true`, then `Queue paused` (flow-2026-11-02.log lines 1851-1852, 17:47:10Z). Next-action text: "Stop using Flow for now, check the Chrome window yourself, then call resume once it loads normally."
- Recovery: `flow_job_control` action `resume` (`rpc.js:182-227`) calls `worker.resume()` which only clears `paused` and kicks (`worker.js:286-291`). It does NOT recheck the page. The held job is `needs_user`; per job-store it can only go to failed or cancelled (`job-store.js:22`), so a new job must be submitted.
- Cooling or backoff: none for WAF. Only the pacer (8-20 s random gap, daily cap, `pacer.js`). Spec says refuse and do not retry (spec line 78, 170).
- How to tell it cleared without credits: the failure is page text, so check the same text the detector reads. Credit-free tools: `flow_status` (reads balance panel, no generation; with `full:true` takes screenshot) and `flow_doctor` (opens and closes panels only). Neither runs `detectBlock`. Practical check: view the Flow project in Chrome and confirm no tile contains "unusual activity"; or `flow_screenshot`. A dry run (`auto_confirm` omitted) spends nothing but does not reach the failing path.
- Interpretation (not proven): the failed tile text says "You have not been charged for this generation" and mentions browser extensions. It sits in project 065acc3b-852c-4cf2-84c6-80359d0543bd (the acceptance project y0-2026-11-02) among tiles. Because the tile persists, any later `observe` poll or failure check on that page would match again, until the tile is deleted (it has a trash icon) or the project is not on screen. Also `credits_at_risk:true` is probably wrong here (log shows `creditsAtRisk:true`, tile says not charged); the balance stayed 792 across the whole third pass (accept3.jsonl).
- Proposed fix for the new plan (not applied): scope WAF text to non-tile areas or exclude `[role=alert]`-less tiles, or match page-level banners only; treat a per-tile "unusual activity ... not been charged" as `FLOW_GENERATION_FAILED` retryable-once with backoff, and keep the full-page WAF only for whole-page interstitials. Decide against evidence from one more screenshot of a real interstitial, which we do not have.

### 2b. Rerun `accept --only 10,11,13,18,19`

Launch (cmd.exe, repo root), through the shim (MCP stdio) into the engine, which uses the owner's Chrome:
```
set FLOW_DATA_DIR=D:\glabs_web\flow-mcp
set FLOW_CDP_PORT=9333
node tests\live\run_acceptance.mjs tools\flow_spike\out\accept4.jsonl --only 10,11,13,18,19
```
Notes: `--only` is by section number. Chrome profile `D:\glabs_web\chrome-profile` on 9333 must already be signed in. `FLOW_TEST_PROJECT` defaults to project 065acc3b-...; `FISH_API_KEY` is only for section 12 (not in this rerun). The runner spawns `mcp/google-flow/src/index.js` as a shim, which starts or joins the engine through `engine.json` in FLOW_DATA_DIR (rule: never use a second data dir). The runner stops if the balance falls 60 credits (`MAX_DROP`).
State dependencies: section 10 needs `st.char` and `st.scene` from sections 8 and 9, and 19 needs the clip from 11.2; because `--only` skips 8, 9, test 10.1 fails with "needs sections 8 and 9", and 19.1/19.2 with "no clip" unless 11 runs in the same invocation (it does). So for 10 to be meaningful use `--only 8,9,10,11,13,18,19` as the third pass did (accept3.jsonl `detail: only 8,9,10,11,13,18,19`). Flag this: the paused-work note's list omits 8 and 9.

| Check | What it does | Credits |
|---|---|---|
| 10.1 | Generates an image with ingredients `{character}` and `{scene}` named from 8/9, `max_credits 1` | 0 (image quota); this is where WAF fired |
| 11.1 | dry-run estimate for Omni 360p 4s silent | 0 (estimate says 4) |
| 11.2 | real Omni 360p 4s silent video, `max_credits 5`; waits up to 25 min; file must be mp4 | about 4 |
| 13.1 | batch dry run (no `auto_confirm`), no run | 0 |
| 13.2 | batch of 2 images, `auto_confirm`, `max_credits 1` | 0 credits, 2 image quota |
| 18.1 | `flow_estimate` of 20 jobs, no browser | 0 |
| 18.2 | same idempotency key twice must return the first job; then finishes one image | 0 credits, 1 image quota |
| 19.1 | `last_frame` of the 11.2 clip to PNG | 0 |
| 19.2 | `stitch_video auto:true` on the run; must output mp4 (bounded by 280 s, see 2e) | 0 |
Total expected: about 4 credits plus quota. Section 7 (incl. 7.6) is not in this list.

### 2c. The 3 live evals

`tests/evals/prompts.json` entries with `live: true`:
- `live1-image` (easy): "Make one image of a red umbrella in project 065acc3b-... and give me the file path." must call `flow_generate_image` and `flow_wait`.
- `live2-pro` (hard): one green apple, Nano Banana Pro at 2K, report file or precisely what stopped it; must `flow_generate_image`, never `flow_generate_video`.
- `live3-continue` (medium): "Continue my last run: find the most recent run, and download its latest asset again without generating." must `flow_list_runs`, never generate image or video.
Harness: a fresh low-context agent (`sonnet-worker`) gets only the MCP, calls tools through `node tests\evals\mcpcall.mjs <log> <tool> <json>` (logs each call as jsonl), then `node tests\evals\score.mjs <log dir> tests\evals\prompts.json tests\evals\production_prompts.json`. Offline evals already logged in `tools/flow_spike/out/evals/` (e1-e5, m1-m4, y1-y6); no `live*.jsonl` exists, so none of the three has been run. `score.mjs` marks any `auto_confirm:true` call as unapproved spend unless the prompt has `live` or `may_start`.
Cost: live1 and live2 are image quota (no credits) per the plan's cost model; Pro quota is not documented, so "unknown". live3 costs 0 (but `flow_download` re-download drives the browser). Plan cap for Y9 live: at most 25 credits. All three need the WAF issue resolved first.

### 2d. Task 19 step 7.6 "still listed"

Code path (test): `tests/live/run_acceptance.mjs`: 7.3 creates `acceptance-<stamp>`, 7.4 renames to `acceptance-<stamp>-renamed`, 7.6 calls `flow_delete_project {url, confirm:true}`, then `flow_list_projects {query:"acceptance-<stamp>"}` and fails if the JSON contains the project's UUID.
Code path (delete): `mcp/google-flow/src/tools/open-project.js:193-228`. `gotoHome` does `page.goto(HOME)`, waits for the account button and project cards; `deleteFromHome` finds the card link `a[href=/project/<id>]`, hovers, clicks Delete, confirms the dialog, then waits for the same link to detach (15 s). If it does not detach it throws `UNKNOWN_UI_CHANGE` "still listed". Listing: `handleListProjects` (`:174`) does a fresh `gotoHome` then `readProjects` (`:149-161`), which reads `a[aria-label="Open project"][href*="/project/"]` anchors and card titles.
Evidence: engine log shows delete returned `ok:true` after 4167 ms (17:17:00), 10643 ms (17:23:07), 14057 ms (17:29:43), 14034 ms (17:35:47). So the in-page verification (link detached) PASSED each time; the test failure is the later fresh listing finding the id. Both failing runs: `accept.log` and `accept2.log`. docs say "a later list showed none". Evidence commit 146a8bf adds only the markdown; no screenshot of the failed listing exists (no `list_projects-error` screenshot saved because nothing threw).
Hypotheses, ranked:
1. Server-side delete lag or soft-delete: Flow's home list (cached or eventually consistent) still returns the card for a short time after the UI removal. Matches "a later list showed none" and delete passing in-page. Decide: poll `flow_list_projects` several times over 60 s after delete, record timestamps; if it vanishes with time, fix the test (retry up to N s), not the tool.
2. Client cache: `page.goto(HOME)` when already on HOME with SPA state reuses cached project data. Decide: compare list after `page.reload()` vs after goto, or list from a fresh tab.
3. Test matching issue: the id check uses `JSON.stringify(list).includes(id)`; list entries are urls with the id, so a different entry cannot match; low probability, but a different project with the same UUID prefix is impossible. Decide: print the matched entry (title+url) on failure.
4. Delete hit the wrong card (path match on `a[href=<pathname>]` is exact, so unlikely) or a Trash/Undo state: Flow has a Trash view (visible in the screenshot sidebar), so deleted projects might first move to Trash and remain addressable. Decide: inspect Trash and the delete dialog text, check whether the project URL still opens.
5. Rename (7.4) created a second card or draft entry for the same project. Decide: list before delete and count entries with this id.
No root cause is claimed. 14.1 deletes a temp project but never relists, so it gives no further evidence. Cheapest next step (credit-free, but needs the WAF clear and a browser): a small controller script that creates, deletes, then lists at 0, 5, 15, 60 s, logging the raw entries.

### 2e. Open decisions

1. stitch_video 280 s cap. Where: `mcp/google-flow/src/engine/stitch.js:13` `LIMIT_MS = 280000` with a comment "runs inside the call, stopped under the shim's 300 s RPC limit; upgrade to a queued job if longer edits are needed". On expiry the timer closes the CLI's stdin, which is the CLI's cancel and removes the partial file (`stitch.js` runCli, about line 52-54). Beyond the cap the stitch is cancelled with no output. Options: (a) keep, and document a clip-count or duration guidance in the tool description; (b) make stitch a queued job in the worker (polled by `flow_wait`), removing the RPC ceiling; (c) raise the cap (the shim limit is 300 s so only a few seconds are available). Recommendation: (b) when assembly work (Phase L3) is scheduled, since long videos with BGM ducking and loudness normalisation will exceed 280 s; until then (a), because stitching is outside the live scope and the cap is safe (no partial file).
2. Amber review bar vs R1. R1 is "Frozen UI vs review in the app" in `docs/superpowers/specs/2026-11-02-youtube-production-design.md:174`: review rows may use only existing status colours, existing buttons/columns, no new page, panel, column or button. Conflict: the Contact Sheet redesign (state file direction contract) reserves amber for live only and red for decisions, while `src/ui/generator/prompt_model.py:35-40` colours `pending_review` and `approved` with the done colour and `regenerating` with the live colour; R1 specifies "existing colours only (amber, green, red, blue)" and a red bar for rejected. The "amber review bar" in the state file is the waiting-for-review colour treatment, which would use amber for a non-live state. Options: (a) follow the owner's new contract: amber = running/regenerating only, review pending shown with ink plus marker, approved/rejected via the marker (state file 3b(b)); (b) keep R1's literal colours; (c) amend R1 in the spec and an ADR. Recommendation: (c) with (a): the owner's later Contact Sheet contract supersedes R1 colours, and the R1 text should be amended so tests (`test_production_rows.py` colour tests) change with a stated reason instead of by drift.
3. flow_list_assets omits audio. Where: `mcp/google-flow/src/engine/rpc.js:286-291`. With `run_id/job_id` it builds assets only from `job.data.outputs` (Flow image/video outputs); with `project_url` it lists the Flow grid (newest 28 tiles). Audio is kept separately on `run.audio` (see `autoSpec` in `stitch.js:30-38`), so voice/bgm/sfx files never appear. Why: audio tools were added after the asset listing; audio files are not Flow tiles. Options: (a) include `run.audio` entries with `kind` ("voice","bgm","sfx"), file, duration, provider; (b) add a separate `audio_list`; (c) leave and document. Recommendation: (a), since agents and the app need one listing for a run, the data is already there and it is a read-only change, with a test.

## 3. Rules a new plan must keep (one line each)

- UI: owner lifted the freeze only for R1 review changes; the Contact Sheet redesign is the owner's later explicit overhaul.
- Never bypass CAPTCHA, verification or limits; no stealth; stop with `needs_user`.
- Never call Flow's internal endpoints (no `batchexecute`); page interaction only through the direct composer.
- No live video outside an owner-approved budget (caps: spike 40, acceptance 300, Y0 15, Y8+Y9 60); live Flow only via the engine controller with a stated budget.
- After `submitted`, never spend again without an explicit retry; the engine reads the quote before Start and stops above `max_credits`.
- One engine per `FLOW_DATA_DIR`; never start a second engine or second tab on the same Chrome (port 9333, profile `D:\glabs_web\chrome-profile`, data dir `D:\glabs_web\flow-mcp`).
- Fish calls always send `model: s2.1-pro-free` unless the caller picks a paid model; Stable audio only an estimate without `auto_confirm` (8 Stability credits).
- No API keys in the repo, config, logs, manifests or screenshots (keys live in Windows Credential Manager).
- Never remove FFmpeg or `src/editor/{model,ffmpeg,subtitles,autoedit}.py`.
- Every Flow label/role lives in `mcp/google-flow/config/ui-contract.json`.
- Offline suites must never start a real browser or spend; new work is proven on real Flow, not the fake.
- A production Animation's deliverable has zero audio streams (proven by ffprobe, original kept in `_original`); a regeneration changes only its own Item and never overwrites files.
- The engine never interprets prose beyond exact-name match; judgement comes via `overrides` or `plan`.
- Agents never self-approve (`actor` forced to `agent` by the shim); `production.json` is review truth with one writer (ADR 0002 still to write).
- Screenshots have a hard 10 s timeout and never fail a job; tolerances: ratio 3%, duration 0.5 s.
- Run `trail check` before each commit; commit only when asked; keep `.claude/session-state.md` current; stay within 300k context.
- Task 19 failures are fixed with `superpowers:systematic-debugging` and a failing test first; report remaining failures plainly.

## 4. Learnings

- `.trail/learnings/` does not exist (no `.trail` directory at all) in D:\Prog\labs-studio-dev. `trail` is installed (`C:\Users\ankit\AppData\Roaming\npm\trail`), but I did not run `trail ask` or `graft note`. `graft` is not on this shell's PATH. So there are no recorded learnings to list; the relevant learning candidates from this inventory:
  - A failed tile's own "unusual activity ... not been charged" text matches the WAF rule and pauses the queue.
  - `accept --only` skips state set by sections 8, 9, 11, so the set must include them.
  - Delete reports success in-page but a fresh list may still show the project (7.6, undiagnosed).
  - `tests/test_stitch.py::test_bgm_ducks_under_voice` hangs intermittently in `src/editor/ffmpeg.py:364`.
