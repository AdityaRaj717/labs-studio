# Agent-Controlled Google Flow MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any MCP agent can run Google Flow image and video work end to end, including batches, YouTube productions with per-item review, and voiceover and audio API access, with durable outputs and truthful live status in Labs Studio. Assembly moves to Later phase L.

**Architecture:** One local Node engine owns Chrome, the queue, pacing, budgets and files. A thin stdio MCP shim and the PySide6 app are both clients of it over token-protected localhost HTTP and SSE.

**Tech Stack:** Node 22, Playwright over CDP, `@modelcontextprotocol/sdk` 1.x, `node:test`; Python 3.12, PySide6, pytest; FFmpeg.

**Spec:** `docs/superpowers/specs/2026-11-02-flow-agent-control-design.md`. Read it before any task; section numbers below refer to it.

## Global Constraints

- UI layout is frozen. Data may flow into existing cells and widgets. No new pages, panels or restyling.
- Never bypass CAPTCHA, verification or limits, and add no stealth. Stop with `needs_user`.
- Never call Flow's internal endpoints. Page interaction only.
- Credits: no live video outside an owner-approved budget. Spike cap 40 credits, acceptance cap 300.
- After `submitted`, never spend again without an explicit retry policy or call.
- Fish calls always send header `model: s2.1-pro-free` unless the caller explicitly picks a paid model.
- Never store API keys in the repo, config, logs, manifests or screenshots.
- Never remove FFmpeg or `src/editor/{model,ffmpeg,subtitles,autoedit}.py`.
- Every Flow label or role lives in `mcp/google-flow/config/ui-contract.json`.
- Offline test suites must never start a real browser against Flow or spend anything.
- Commit per task on branch `feat/flow-agent-control`, not `main`. Attribution per the session's rule.

## Build Rules (these override anything below that conflicts)

From the independent review of this plan:

- **Paths:** Node files in Tasks 2-11, 15 and the `.js` files in 16 and 18 are relative to `mcp/google-flow/`. Python files are relative to the repo root.
- **Chrome owner:** the engine launches and attaches to Chrome (port 9333, profile `D:\glabs_web\chrome-profile`, both from existing settings passed by env). In Task 13, `src/web/session.py` stops opening its own tab; login check and bring-to-front become engine RPCs, used by `web_sessions_tab.py`. Add a grep test for `labs.google` and `Profile 3` over `src/web`.
- **Pacing and labels:** Task 13 deletes `src/web/pacing.py` and pushes the daily-cap and gap settings to the engine. App-side options in `src/web/selectors/flow.json` are replaced by `flow_capabilities`.
- **Task 2 is a hard gate:** no approval means stop before Task 3. If Flow offers no way to set a duration or resolution, remove that option from Task 6 and Task 10 args, estimate from what Flow reports, and record the change in the spec. Don't guess.
- **Stitcher runtime:** this repo's `.venv` is required, found via engine setting `pythonPath`, default `<repo>/.venv/Scripts/python.exe`; if it's missing, return a clear error with the setup command. The CLI is `python -m src.stitch_cli`. Packaged-installer support is out of scope until the owner wants an installer.
- **Credit ledger:** Task 7 also creates `src/engine/ledger.js` with `recordSpend(job, credits)`, `monthTotal()`, `todayQuota(model)`, persisted in the data dir. It backs `checkBudget` and `flow_status`.
- **Tool registration:** Task 8 registers the whole list from spec 6.4 so the list test pins it. Tools not built yet return `NOT_IMPLEMENTED`, and the test that none remain goes in Task 19. Task 8 wires `flow_doctor`, `flow_capabilities`, `flow_status`, `flow_screenshot`.
- **Old queue:** Task 8 keeps `job-queue.js` behind a worker adapter and switches `flow-status.js` to the job store. Task 9 deletes it, not Task 8.
- **Order:** run tasks strictly in order from Task 12 on, since `src/features.py` is shared. Task 12 keeps a reduced `features.py`. `flow_video` stays hidden after Gemini is removed, and Task 14 shows it with the new provider. Task 12's before-and-after check covers the default visible pages only.
- **Scope details:** Task 9 owns session reset and asset info (read into verification). Tasks 9 and 10 own upscaling through download sizes. Run cleanup uses `flow_delete_project` with confirm; trash controls are out of this version. Task 1 adds the two testing docs where they are, with no move.
- **Live coverage:** Task 19 also runs guide section 7 and 14 cross-project flows, rewritten section 11 video tests, and section 17 end-to-end scenarios, with section 12 removed.

## Spike rulings (from Task 2, these override everything below; facts in `docs/flow-ui-findings.md`)

- **Direct composer (C10):** generation closes the chat panel and turns the Agent toggle off, asserted each job. Replace `neverConfirm` with this. Drop `AGENT_NEEDS_CLARIFICATION` tests and the agent turn logic; keep the code in the enum only for Python mapping. Review Focus 3 becomes: wrong count or ratio is not success, and a job with no new tile in 60s fails without hanging.
- **Quote gate (C12):** `applySettings` reads the settings back, then reads `link "N credits"`. Above `max_credits` is `BUDGET_EXCEEDED`, no spend. `quotedCredits` goes in the manifest and ledger. `getBalance(page)` reads the account panel; `flow_status` includes it.
- **Observe tiles only:** a generation is identified by new tiles at the top versus the count before submit. `n%` text gives `progress` with `source: 'flow'`, and it isn't linear. Done is a finished media element. A tile leaving the running state without one is failed with its text saved.
- **Capabilities:** Veo Lite, Fast, Quality accept `duration` 8 or omitted and `resolution` 720p or omitted; anything else is `COMBINATION_NOT_SUPPORTED`, and no control is touched. Extend only from Veo clips. Task 6's `ingredients with 4s Veo Lite rejected` stays true, and 4s on Veo is rejected in every mode.
- **Silent (C11):** `silent: true` runs `ffmpeg -an -c copy` after download, keeps the original, and `verifyVideo` checks the copy has no audio stream. Replaces the toggle test in Task 10.
- **FFmpeg path:** the engine setting `ffmpegPath`, env `FFMPEG_PATH`, default PATH then `D:\Apps\ffmpeg\ffmpeg-9.0.2-essentials_build\bin`. FFprobe sits beside it. Owner's PATH isn't changed.
- **Images:** downloads are JPEG, extension from the suggested filename. Ratio tolerance 3%, duration tolerance 0.5s.
- **Screenshots:** hard 10s timeout, never fail a job on one.
- **C6 settled:** `grid-architect.js` is deleted in Task 4.
- **`npm test`** is `node --test test/*.test.js`; bare `test/` fails on Node 22.

## YouTube production phase (added 2026-11-02; these override anything below that conflicts)

Plan: `docs/superpowers/plans/2026-11-02-youtube-production.md`. Spec: `docs/superpowers/specs/2026-11-02-youtube-production-design.md`. Y tasks slot into this plan, with **order:** 1-4 (done) → **Y0** → 5-8 → 9-11 → **Y1-Y5** → 12-14 → **Y6, Y7** → 15, 16 → **Y8** → 19 → **Y9** → 20 → Phase L.

- **Later phase (L):** Task 18 whole; Task 16's voice row and `preview_voice`; Task 17; the stitch and music parts of Task 19; the assembled-video eval in Task 20. FFmpeg, `src/editor/{model,ffmpeg,subtitles,autoedit}.py` and `last_frame_cmd` stay, per Global Constraints.
- **Tool list:** `stitch_video` is not registered. Task 8 pins spec 6.4 minus it and asserts it's absent; Y tasks add theirs. Task 19's no-`NOT_IMPLEMENTED` test covers that list. L1 registers it.
- **Silent:** Task 10 builds `src/flow/silent.js` this way: `stripAudio(file, {ffmpegPath}) -> {file, original, audio_streams}`. The stripped file is the deliverable under the normal name, the original moves to `videos/_original/<stem>.flow.mp4`, and a repeat strips from the existing original. Task 10 adds tests `stripAudio on a testsrc plus sine clip leaves zero audio streams and keeps duration within 0.5s`, `the original still has one audio stream`, `repeating stripAudio doesn't lose the original`, and `verifyVideo with an audio stream in the deliverable is RESULT_MISMATCH`.
- **Task 20:** adds the YouTube spec's vocabulary to `GLOSSARY.md`, and writes `docs/adr/0002-production-review-state.md` (production.json as review truth, one writer). Assembly steps inside guide section 17 and the T-17 campaign are Later phase L3.
- **UI freeze:** the owner lifted it only for the review list in YouTube spec R1, applied in Y6 and Y7. Otherwise frozen.
- **Stitcher runtime** Build Rule applies from L1.

## Review Focus

1. **Crash or reboot just after Start is clicked:** no second spend; the result is recovered from the project or marked `credits_at_risk`. Test in Task 5.
2. **Owner clicks around in the Flow tab, or closes Chrome, mid-batch:** the current job fails clearly, the rest stay queued and resumable. Test in Task 8.
3. **Flow's agent asks a question or makes the wrong count or ratio:** not reported as success, no hang until timeout. Test in Task 9.
4. **Output folder unwritable or disk full after generation:** the generation isn't repeated, and download can be retried. Test in Task 9.
5. **Unicode, very long, or duplicate prompts and filenames, including a repeat of the same request:** safe Windows paths, no overwrite, and the idempotency key returns the first job. Test in Task 6.

## Capabilities by phase

Use what's listed; names are installed skills or MCP servers.

| Phase | Use |
|---|---|
| All coding | `/ponytail` once per session, `superpowers:test-driven-development`, `superpowers:verification-before-completion`; `executor` agents for approved tasks, `sonnet-worker` for tests and docs; `codebase-memory-mcp` for callers |
| Phase 0-1 | `superpowers:using-git-worktrees`, `chrome-devtools` MCP for the spike, `playwright-cli`, `superpowers:systematic-debugging` |
| Phase 2 | `api-and-interface-design`, `backend-reliability`, `error-handling-patterns`, `observability-and-instrumentation`, `codebase-design`; `security-and-hardening` for the local server and tokens |
| Phase 3 | `playwright-cli`, `web-qa`-style checks on fake Flow; `superpowers:systematic-debugging` for live drift |
| Phase 4 | `code-simplification`, `/code-review` |
| Phase 5 | `context7` for SDK docs, `error-handling-patterns`, `security-and-hardening` |
| Phase 6 | `superpowers:requesting-code-review`, native `/security-review`, `gitleaks` and `osv-scanner` by full path, `claude-md-improver`, `domain-modeling` for ADR and glossary, `superpowers:finishing-a-development-branch` |

Session rule: keep `.claude/session-state.md` current and start a new session per phase or at 300k context.

---

## Phase 0: Ground truth

### Task 1: Working baseline

**Files:**
- Modify: `mcp/google-flow/package.json`, `.gitignore`
- Create: `.claude/session-state.md`, `mcp/google-flow/test/smoke.test.js`
- Move: `docs/AGENT_CONTROL_TESTING_ISSUES.md`, `docs/agent_control_testing_guide.md` (commit as-is)

**Interfaces:**
- Produces: `npm test` runs `node --test test/`.

- [ ] **Step 1:** Create branch `feat/flow-agent-control`. Run `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt pytest`, `npm ci` in `mcp/google-flow`.
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest -q`. Record pass count in the state file. Expected: all pass; investigate anything else before continuing.
- [ ] **Step 3:** Install FFmpeg: `winget install -e --id Gyan.FFmpeg`. Verify `ffmpeg -version`. (It's missing from PATH today.)
- [ ] **Step 4:** Set `"test": "node --test test/"`. Add `smoke.test.js`: spawn `src/index.js`, send `initialize` and `tools/list` over stdio, assert the list is non-empty. Run; expected PASS.
- [ ] **Step 5:** Commit.

### Task 2: Paid observation spike (needs owner approval, cap 40 credits)

**Files:**
- Create: `tools/flow_spike/record.mjs`, `docs/flow-ui-findings.md`, `mcp/google-flow/test/fixtures/snapshots/*.txt`

**Interfaces:**
- Produces: findings consumed by Tasks 3, 7, 9, 10, 11; recorded snapshots for fake Flow.

- [ ] **Step 1:** Write `record.mjs <project-url> <label>`: attach over CDP, then every second save an accessibility snapshot diff and timestamp until told to stop. Save snapshots only with account email masked. Save request method and path names, no bodies or tokens.
- [ ] **Step 2:** In a new project named `spike-<date>`, record each and write what's on screen into `flow-ui-findings.md`:
  - 1 image, x1, Nano Banana 2.1 (no credits): tile loading state, any percentage, gallery timing, what confirms done.
  - 1 image x2, with an upload reference.
  - 1 Omni 1.1 Flash video at 360p and 4s if settable (4 credits): how duration and resolution are chosen, what the composer says, progress display, done state, video editor view, download menu.
  - 1 Veo 3.1 Lite (10): how the model is obeyed, start frame.
  - One Omni 720p 4s (7), with Return silent videos on, checked with ffprobe.
- [ ] **Step 3:** Record without spending: where the credit balance is shown; home-page lazy loading; delete dialog text (cancel it); Characters tile list, first and last frame entry, and Extend entry points; Grid Architect reachability (decides C6); collapsed chat behaviour; error toast selectors if any occur.
- [ ] **Step 4:** Try safe failure paths: prompt Flow's agent likely answers with a question rather than generating (for example "what can you do?"), which spends nothing. Record the reply's structure.
- [ ] **Step 5:** Note credits spent. Commit findings and snapshots. Update spec section 4.2 and open items with facts. If Flow shows no percentage, record it; progress stays `phase`.

---

## Phase 1: Stop the known bleeding

### Task 3: UI contract and doctor

**Files:**
- Create: `mcp/google-flow/config/ui-contract.json`, `src/flow/contract.js`, `src/tools/doctor.js`, `test/contract.test.js`, `test/fake-flow/server.js`, `test/fake-flow/pages/*.html`
- Delete: `config/selectors.map.json`, `src/tools/discover-ui.js`, `src/tools/flow-open.js`

**Interfaces:**
- Produces: `locate(page, key, opts?) -> Locator`; `closeOverlay(page)` closing by control or backdrop, never Escape alone; `findSettingsGroup(page, 'image.aspect'|'image.count'|'video.aspect'|'video.count') -> Locator` by the preceding text label; `runDoctor(page) -> { ok, checked, missing:[{key,where}], host }`; `startFakeFlow({scenario}) -> {url, close}`.

- [ ] **Step 1:** Write tests: `locate resolves every contract key against fake Flow`; `findSettingsGroup finds image.count without index`; `closeOverlay closes the settings panel on a page that ignores Escape`; `doctor reports a missing Start button with its key`.
- [ ] **Step 2:** Run; expect failure on missing modules.
- [ ] **Step 3:** Build the contract with real labels from spec 4.2 and Task 2, per page: home, project, settings, picker, editor, character. Build fake Flow from the recorded snapshots with scenario switches. Implement locate, close, groups, and doctor (opens panels, reads, closes, never saves).
- [ ] **Step 4:** Run tests; expect PASS. Run the doctor live once; expect `ok:true`.
- [ ] **Step 5:** Commit.

### Task 4: Clear the logged issues in the code that stays

**Files:**
- Modify: `src/browser/launch-profile.js`, `src/browser/connect.js`, `src/browser/account-check.js`, `src/browser/safe-actions.js`, `src/navigation/project-navigator.js`, `src/tools/open-project.js`, `src/tools/flow-status.js`, `src/tools/create-character.js`, `src/utils/config.js`, `config/flow.config.example.json`
- Delete: `src/tools/open-tools-gallery.js`, `src/tools/use-flow-tool.js`; `src/tools/grid-architect.js` per Task 2
- Test: `test/issues.test.js`

Issue map: #1 networkidle, #2 host check, #3 French labels, #5 `full`, #6 delete race, #8 discover (done in Task 3). #4 and #7 are in Task 6; #9 in Task 9.

**Interfaces:**
- Produces: `isFlowHost(url) -> bool`; `launchFlowChrome()` replacing `launchKiaraProfile`; `waitForProjectCards(page)`; config `videoModels` with `Omni 1.1 Flash` plus alias `Omni Flash`; `videoRatios` `["16:9","9:16"]`.

- [ ] **Step 1:** Write tests: `no source file contains networkidle`; `no source file contains French labels or labs.google/fx` (grep list from spec 4.1); `isFlowHost accepts flow.google.com`; `status with full:true includes a screenshot path`; `delete waits for slow cards` (fake Flow scenario, 4s delay); `delete succeeds when list refresh is slow`; `account check fails when expected account is set and differs, and reports unverified when none is set`; `closing the MCP doesn't close Chrome`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Fix. `waitUntil: 'domcontentloaded'` plus a contract element wait. `flow_disconnect` detaches only; verify the CDP close doesn't terminate Chrome in the live tier.
- [ ] **Step 4:** Run tests; expect PASS. Commit.

---

## Phase 2: Engine

### Task 5: Durable job store and queue

**Files:**
- Create: `src/engine/journal.js`, `src/engine/job-store.js`, `src/engine/run-folder.js`, `test/job-store.test.js`
- Delete: `src/queue/job-queue.js` at Task 8 cutover

**Interfaces:**
- Produces:
  - `createRun({name, outputRoot, flowProjectUrl}) -> Run`, with folders per spec 6.3.
  - `appendEvent(run, event)` assigns monotonically increasing `seq`, written and fsynced to `events.jsonl`.
  - `writeManifest(run)` atomic (temp plus rename).
  - `enqueue(run, jobSpec, idempotencyKey) -> Job`; `transition(job, state, data)`, rejecting illegal moves per spec 6.1.
  - `recover() -> { resumable: Job[], reconcile: Job[] }`.

- [ ] **Step 1:** Write tests:
  - `transition rejects done from queued`.
  - `submitted event is on disk before the callback returns`.
  - `recover returns a job at submitted in reconcile, not resumable`, the Review Focus 1 test.
  - `recover resumes a job at preparing`.
  - `manifest survives a torn temp file`.
  - `same idempotency key returns the same job`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS. Commit.

### Task 6: Input validation and capabilities

**Files:**
- Create: `src/engine/capabilities.js`, `src/engine/validate.js`, `src/engine/budget.js`, `src/engine/filenames.js`, `test/validate.test.js`, `test/filenames.test.js`
- Create: `config/capabilities.json`

**Interfaces:**
- Produces:
  - `getCapabilities() -> {image, video, limits, verifiedAt}`, with spec 4.3 values.
  - `validateImage(args) -> normalized | throws FlowError`; `validateVideo(args)` likewise.
  - `estimate(jobSpecs) -> {credits, imageQuota:{model:count}, warnings}`.
  - `checkBudget(estimate, maxCredits, ledger)`.
  - `assetName(seq, prompt, version, ext, dir) -> path`.

- [ ] **Step 1:** Write tests with spec's exact values:
  - `empty, whitespace and missing prompt are INVALID_PARAMS with no page use` (#4); `missing reference path is INVALID_PARAMS naming the file` (#7).
  - `count 0, 5 rejected`; `7:3 lists valid ratios`; `video 1:1 rejected`; `4K rejected on Pro with a next_action`.
  - `ingredients with Veo Quality is COMBINATION_NOT_SUPPORTED`; `ingredients with 4s Veo Lite rejected`; `Omni 10s 720p estimates 15`, `Veo Lite estimates 10`, `Veo Quality 100`, `x2 doubles`.
  - `images estimate 0 credits and count against quota`; `spend above max_credits is BUDGET_EXCEEDED`.
  - `assetName handles Japanese, reserved names (CON), 5000 characters, and never overwrites`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS. Commit.

### Task 7: Tab lock, pacing, blocks, and error contract

**Files:**
- Create: `src/engine/tab-lock.js`, `src/engine/pacer.js`, `src/flow/blocks.js`, `test/guards.test.js`
- Modify: `src/utils/errors.js`

**Interfaces:**
- Produces:
  - `withTab(label, fn)`; serialises all browser access.
  - `pacer.waitTurn(signal)`, `pacer.recordUse()`, `pacer.capReached()`, persisted per local day.
  - `detectBlock(page) -> null | {code, text}`, checking URL, text, toasts and `[role=alert]`.
  - `toErrorPayload(err) -> {ok:false,error_code,message,retryable,credits_at_risk,next_action,details,screenshot}` covering all codes in spec 6.5.

- [ ] **Step 1:** Write tests: `a screenshot during a job waits for the tab lock`; `pacing is enforced across two client calls`; `cap persists across restart`; `detectBlock maps sign-in URL, CAPTCHA text, quota text, unusual activity text`; `every ErrorCodes value has a class and a next_action`.
- [ ] **Step 2:** Run, implement, run; expect PASS. Commit.

### Task 8: Engine server, shim, and tool surface

**Files:**
- Create: `src/engine/server.js`, `src/engine/worker.js`, `src/engine/start.js`, `src/shim/client.js`, `src/shim/tools.js`, `src/shim/guide.md`, `test/engine.test.js`
- Modify: `src/index.js` (shim only)
- Delete: `src/queue/job-queue.js`

**Interfaces:**
- Consumes: Tasks 5-7.
- Produces:
  - HTTP on 127.0.0.1, `Authorization: Bearer <token>`: `POST /rpc {tool,args}`, `GET /events?since=<seq>` (SSE, replay then live), `GET /health`, `POST /secrets`.
  - `ensureEngine() -> {url, token}` via `<dataDir>/engine.json`, handling stale lock and version mismatch.
  - Tools per spec 6.4, with annotations and server `instructions`. `flow_wait({job_id|run_id, wait_ms<=55000})`; the MCP progress token is honoured when the client sends one.

- [ ] **Step 1:** Write tests:
  - `two shims share one engine`; `request without token is 401`; `engine binds 127.0.0.1 only`; `stale lock file starts a new engine`.
  - `SSE replays from since and has no gaps`.
  - `a second generate queues rather than raising JOB_IN_PROGRESS`.
  - `flow_wait returns within wait_ms with current state`.
  - `tools/list has annotations and each delete is destructive`; `tools/list contains no removed names`; `flow_delete_project without confirm doesn't touch the page`.
  - `concise response stays under 2,000 tokens for a 200-job run`.
  - Review Focus 2: `Chrome closing mid-batch fails the current job with BROWSER_NOT_CONNECTED and leaves others queued`; `page navigated by a person yields a clear failure, not a wrong download`.
- [ ] **Step 2:** Run; expect failure. Implement. Keep the old image flow behind the worker until Task 9.
- [ ] **Step 3:** Run; expect PASS. Check with `@modelcontextprotocol/inspector`-style stdio smoke. Commit.

---

## Phase 3: Generation

### Task 9: Image pipeline rewrite

**Files:**
- Create: `src/flow/session.js`, `src/flow/settings.js`, `src/flow/ingredients.js`, `src/flow/observe.js`, `src/flow/download.js`, `src/flow/verify.js`, `src/flow/image.js`, `test/image.test.js`
- Delete: `src/tools/generate-image.js`, `src/tools/download-latest.js`, `src/utils/file-manager.js` after moving what's useful

**Interfaces:**
- Consumes: contract, journal, tab lock.
- Produces:
  - `applySettings(page, {kind, ratio, count, model, neverConfirm})`; reads back and asserts each radio and model.
  - `addIngredient(page, {file|character|scene|project})`, with 3-try stalled-upload handling.
  - `observeGeneration(page, {turnsBefore, onUpdate, signal}) -> {status, images, text, error}`; ends on done, error bubble, block, question, or timeout, and calls `onUpdate({progress, source, previewPath})` per spec 6.2.
  - `downloadAsset(page, item, {size, dest})`, retry-safe.
  - `verifyImage(file, request) -> {ok, mismatches}`.
  - `runImageJob(ctx, job)`.

- [ ] **Step 1:** Write fake Flow tests:
  - `happy path saves x2 files named by assetName with manifest fields`.
  - `error bubble fails fast within 5s, not at timeout` (#9).
  - `agent question is AGENT_NEEDS_CLARIFICATION` (Review Focus 3).
  - `one image when x2 requested is RESULT_MISMATCH and keeps the file` (Review Focus 3).
  - `wrong dimensions for 16:9 is RESULT_MISMATCH`.
  - `quota text pauses the run`, `CAPTCHA page sets needs_user and brings the window forward`.
  - `unwritable output keeps the job downloadable and doesn't regenerate` (Review Focus 4).
  - `settings readback mismatch throws before submit`.
  - `auto_confirm false stops before Start and spends nothing`.
  - `submitted is journaled before Start is clicked`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS.
- [ ] **Step 3:** T3 live: one image at x1 and x2 at 2K. Verify files open. Commit.

### Task 10: Video pipeline, built new

**Files:**
- Create: `src/flow/video.js`, `test/video.test.js`
- Delete: `src/tools/generate-video.js`
- Modify: `src/flow/verify.js`, `src/flow/settings.js`

**Interfaces:**
- Consumes: Task 9 functions; duration and resolution method from Task 2.
- Produces: `runVideoJob(ctx, job)`; job args `prompt, model, ratio, duration, resolution, count, start_frame, end_frame, ingredients, extend_from, edit_from, silent, auto_confirm, max_credits`; `verifyVideo(file, request)` using ffprobe.

- [ ] **Step 1:** Write fake Flow tests: `text-to-video downloads an mp4 with manifest and estimated credits`; `start frame is attached`; `first and last frames`; `ingredients uses 8s`; `extend targets the source clip`; `edit estimates 40`; `silent sets the toggle and verifies no audio stream`; `10-minute generation survives with flow_wait polling`; `safety block records a refund note`; `duration mismatch is RESULT_MISMATCH`; `no auto_confirm spends nothing`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS.
- [ ] **Step 3:** T4 live within budget: Omni 360p 4s, then Veo Lite with start frame. Record real credit change. Commit.

### Task 11: Batch, reconcile, projects, characters

**Files:**
- Create: `src/engine/batch.js`, `src/flow/reconcile.js`, `test/batch.test.js`
- Modify: `src/tools/open-project.js`, `src/tools/create-character.js`, `src/tools/create-scene.js`, `src/tools/import-character.js`

**Interfaces:**
- Produces: `flow_batch_start({name, jobs|file, defaults, project, max_credits, stop_on, auto_confirm}) -> {run_id, queued, estimate}`; `reconcile(page, job) -> {found, assets}`; `flow_job_control`; `flow_list_runs`; `flow_list_assets`; `flow_download`; `flow_estimate`.

- [ ] **Step 1:** Write tests:
  - `a 200-job mixed batch estimates before any browser use`; `budget overrun rejects at start`.
  - `one refused job doesn't stop the rest`; `quota stops the rest as resumable`; `resume runs only unfinished`; `retry_failed runs only failed and asks for spend budget`; `cancel lets the current job finish its download`.
  - `kill engine at each state then restart: no second Start click` (uses fake Flow's click counter).
  - `reconcile finds a result completed while the engine was down`.
  - `character not found fails before Start and lists existing names`; `characters don't leak across projects`.
  - JSON and CSV input.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS.
- [ ] **Step 3:** T3 live: 10-image batch with a character and a scene; kill the engine mid-run; restart; confirm no duplicate. Commit.

---

## Phase 4: App

### Task 12: Remove unrelated features

**Files:** per audit. Delete `src/gen/{gemini_image,gemini_video,grok,openai_image,http_common}.py`, `src/workflow/`, `src/ui/workflow/`, `src/ui/editor/`, `src/ui/tools/`, `src/tools/{realesrgan,tasks}.py` with tests and help; modify `src/app.py`, `src/ui/sidebar.py`, `src/ui/main_window.py`, `src/features.py`, `src/characters/voices.py`, `src/ui/characters/page.py`, `src/languages/en.py`, `src/webhook/*`, `src/ui/webhook/*`, `packaging/labs_studio.spec`, `tools/make_help_screenshots.py`, `help/en/*`, `tests/*`; move `src/gen/fake_provider.py` to `tests/fake_provider.py`.

**Interfaces:**
- Produces: `src/tools/ffmpeg.py` keeps `last_frame_cmd`; single setting `tools.ffmpeg_path`; `features.py` removed or reduced with flow strings hard-coded; `Character.voice` kept as a Fish `reference_id`; `preview_voice` removed until Later phase L2.

- [ ] **Step 1:** Add test `test_nav_visible_default` capturing the current default sidebar keys before any deletion. Run; PASS.
- [ ] **Step 2:** Remove one feature per commit in this order: placeholders, workflow, upscaler and Video Cut, GUI editor, Grok and OpenAI, Gemini, demo (moving the fake to tests, retargeting webhook default to `flow_image`). Run pytest after each; expect PASS with removed tests gone.
- [ ] **Step 3:** Render default Flow pages before and after with `tools/make_help_screenshots.py`; view and compare. Expected: same layout.
- [ ] **Step 4:** `grep -ri "gemini\|grok\|openai\|workflow" src tests help` shows only intended uses. Commit.

### Task 13: App on the engine, live sync

**Files:**
- Create: `src/web/engine_client.py`, `tests/test_engine_client.py`
- Modify: `src/web/flow_mcp.py`, `src/gen/provider.py`, `src/gen/models.py`, `src/gen/queue.py`, `src/gen/web_flow_image.py`, `src/ui/generator/prompt_model.py`, `src/web/session.py`, `src/characters/flow_sync.py`
- Delete: `src/web/mcp_client.py` only when no caller remains

**Interfaces:**
- Produces:
  - `EngineClient.ensure()`, `.call(tool, args, timeout)`, `.events(since) -> iterator`, reconnecting with `since`.
  - `RunContext.partial(path)`, new with default no-op; sets `Job.preview`.
  - `prompt_model` output cell falls back to `job.preview` when `job.outputs` is empty.

- [ ] **Step 1:** Write tests using a fake engine: `progress event updates job.progress`; `partial sets preview and the output cell's DecorationRole is a thumbnail`; `final outputs replace preview`; `SSE reconnect replays missed events`; `error codes keep mapping` (existing tests adapted); `app restart rebuilds rows from manifests`; `source phase is not shown as Flow's own percent in tooltip`.
- [ ] **Step 2:** Run; expect failure. Implement. Remove temp-folder deletion: the provider points at permanent run folders, not `flow_tmp`.
- [ ] **Step 3:** Run; expect PASS. Live: start a job in the app, watch the bar and thumbnail against Chrome. Commit.

### Task 14: External agent runs appear in the app, and Flow video page

**Files:**
- Create: `src/web/run_mirror.py`, `src/gen/web_flow_video.py`, `tests/test_run_mirror.py`, `tests/test_web_flow_video.py`
- Modify: `src/app.py`, `src/ui/sidebar.py`, `src/ui/generator/page.py`, `src/projects/store.py`, `src/features.py`

**Interfaces:**
- Produces: `RunMirror.start(store)`, mapping `manifest.flowProjectUrl` to a project (creating one if none), adding rows to `flow_image` or `flow_video` tagged `origin='agent'`; `WebFlowVideoProvider` with fields model, ratio, duration, resolution, silent, reusing existing `ConfigField` widgets.

- [ ] **Step 1:** Write tests: `agent job adds exactly one row`; `an app-started job isn't mirrored twice`; `rows update through done`; `closed-app run shows after reopening`; `row Start on an agent row doesn't resubmit a done job`; `video provider rejects invalid mixes before a call`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS.
- [ ] **Step 3:** Live: an agent starts an image and a 4s Omni 360p; app shows both with thumbnails and final files. Compare layout screenshots. Commit.

---

## Phase 5: Audio and assembly

### Task 15: Fish Audio

**Files:**
- Create: `src/audio/fish.js`, `test/fish.test.js`
- Modify: `src/shim/tools.js`, `src/engine/server.js`

**Interfaces:**
- Produces: `audio_voice_generate({text|script, voice_id, run_id, name, format='mp3', speed, volume, temperature, top_p, model='s2.1-pro-free', language})`; `audio_voice_list({query, mine})`.

- [ ] **Step 1:** Write tests with mocked `fetch`: `model header is always sent`; `default is s2.1-pro-free`; `402 is AUDIO_NO_CREDIT with no fallback to paid`; `429 backs off up to 3 times`, `503 retries`; `401 is MISSING_API_KEY style with next_action`; `long text splits on sentence boundaries, joins in order, reports segments`; `file lands in voice/ with manifest entry`; `the key never appears in logs, events, manifest or errors`; timeouts abort at the limit.
- [ ] **Step 2:** Run; expect failure. Implement with 120s timeout per request and concurrency 1.
- [ ] **Step 3:** Run; expect PASS. Live: one sentence on the free model using the owner's key (key entered by owner). Listen check by owner. Commit.

### Task 16: Stable Audio 3, keys

**Later phase L2 (not in this task):** the character voice row, and changes to `src/ui/characters/page.py` and `src/characters/voices.py`.

**Files:**
- Create: `src/audio/stable.js`, `src/keys_push.py`, `test/stable.test.js`, `tests/test_audio_keys.py`
- Modify: `src/keys.py`, `src/ui/pages/settings_page.py`, `src/features.py`

**Interfaces:**
- Produces: `audio_stable_generate({kind:'music'|'sfx', prompt, duration, seed, steps=8, cfg_scale=1, output_format='wav', run_id, name, auto_confirm})`, charged at 8 Stability credits; `pushKeys(engine)`.

- [ ] **Step 1:** Write tests: `multipart body has spec's fields`; `202 then poll then saved in bgm/ or sfx/`; `poll has a bounded timeout`; `403 is SAFETY_BLOCKED; 402 is AUDIO_NO_CREDIT; 422 fails the job`; `no auto_confirm returns an estimate only`; `results are saved before reporting done`; Python: `keys tab lists Fish and Stability only`, `pushKeys posts to /secrets`, `no key means a clear error`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS.
- [ ] **Step 3:** Live: one 10s SFX (8 of the 25 free Stability credits). Commit.

### Task 17: Optional local Small models (only if the owner chooses)

**Later phase.** Skipped by default per C4. If chosen: separate venv under `tools/stable_audio/`, `backend: 'local'` on the same tool, Small music and SFX only, and the owner accepts the gated licence on Hugging Face personally.

### Task 18: Stitcher

**Later phase L1. Not in the current order;** kept here as the brief for L1.

**Files:**
- Create: `src/editor/stitch.py`, `src/stitch_cli.py`, `tests/test_stitch.py`, `mcp/google-flow/test/stitch.test.js`
- Modify: `src/editor/ffmpeg.py` (`build_export`), `src/editor/model.py`, `src/shim/tools.js`, `src/engine/worker.js`

**Interfaces:**
- Produces:
  - `stitch(spec: StitchSpec, on_progress, should_stop) -> Path`, Qt-free, built on `run_export`.
  - Spec fields: `clips:[{path,trim_start,trim_end,hold}]`, `voice:[{path,start}]`, `bgm:{path,volume,fade_out,duck}`, `sfx:[{path,start,volume}]`, `transition:{type,duration}`, `size`, `fps`, `loudness=-14`, `output`.
  - CLI `python -m src.stitch_cli <spec.json>`, JSON progress lines on stdout. Engine setting `pythonPath`.
  - `stitch_video({run_id, spec|auto:true, name})`, where `auto` orders run videos by seq and uses voice and BGM.
  - `last_frame(run_id, asset_id)` used for chaining.

- [ ] **Step 1:** Write tests with tiny clips generated by ffmpeg (`testsrc`, `sine`): `two clips join with correct duration`; `9:16 and 16:9 mix is letterboxed to spec size`; `silent clip plus voice has audio`; `BGM ducks under voice` (measure level during and outside voice with `volumedetect`); `loudness is within ±1 LU of -14`; `missing input lists the path`; `FFMPEG_NOT_FOUND has install step`; `originals are untouched`; `cancel removes partial output`.
- [ ] **Step 2:** Run; expect failure. Implement, including `sidechaincompress` in `build_export`.
- [ ] **Step 3:** Run; expect PASS. Watch a real output with audio. Commit.

---

## Phase 6: Proof

### Task 19: Rewrite the test guide, run all live tiers

**Files:**
- Modify: `docs/agent_control_testing_guide.md`, `docs/AGENT_CONTROL_TESTING_ISSUES.md`
- Create: `docs/flow-live-acceptance.md`, `tests/live/run_acceptance.mjs`

- [ ] **Step 1:** Update guide: new tool names, real model names, `auto_confirm: true` where generation is meant, and a credit column. Each test must assert a file exists and is valid, not a status. Remove Gemini, Grok and OpenAI tables.
- [ ] **Step 2:** Run sections 1-10, 13-16, 18 on images. Video with Omni 360p unless the test is about another model. Add voice and SFX API tests. Stitch, music and assembled-video tests are Later phase L3.
- [ ] **Step 3:** Record each result with evidence path and credit use. Stop at 300 credits, counting Y0's video leg, Y8 and Y9 if the owner put them inside the cap. Fix failures through `superpowers:systematic-debugging`, adding a failing test first. Report any remaining failure plainly.

### Task 20: Cold-agent evals, docs, final review

**Files:**
- Create: `tests/evals/prompts.json`, `tests/evals/score.mjs`, `docs/adr/0001-flow-engine.md`, `GLOSSARY.md`, `CLAUDE.md`, `.github/workflows/test.yml`
- Modify: `README.md`, `help/en/mcp-agents.md`, `help/en/*`, `mcp/google-flow/README.md`, `src/shim/guide.md`

- [ ] **Step 1:** Extend Y9's `tests/evals/score.mjs` with about 15 eval prompts, from "make one image" through the T-17 campaign, a failure in the middle, and "continue yesterday's run". (A story with narration and music assembled is Later phase L3.) Run each with a fresh low-context agent (`sonnet-worker`) given only the MCP. Score completion, tool-call count, and wrong calls. Fix tool descriptions and errors, not the prompts. Target: 100% on easy, at least 90% overall, no unapproved spend.
- [ ] **Step 2:** Docs: config for Claude Code, Claude Desktop, Cursor, Codex; recovery guide; updated help; CI running Node and Python offline suites on `windows-latest`; regenerate help screenshots.
- [ ] **Step 3:** Run `node --test`, pytest, `gitleaks` with `--redact`, `osv-scanner`, `/security-review`, and a whole-branch review. Fix findings.
- [ ] **Step 4:** Use `superpowers:finishing-a-development-branch`. Then ask the owner for the UI overhaul brief.

---

## Dependency order

Task 1 → 2 → 3 → 4 → **Y0** → 5, 6, 7 → 8 → 9 → 10 → 11 → **Y1 → Y2 → Y3 → Y4 → Y5** → 12 → 13 → 14 → **Y6 → Y7** → 15 → 16 → **Y8** → 19 → **Y9** → 20 → Later phase L (18, 17 if chosen, voice and assembly). Tasks 5, 6, 7 are independent of each other. So are 12 and 15, 16 once 8 is done, but this order is what's planned.

## Owner checkpoints

1. Before Task 2: approve up to 40 credits. (Done.)
2. Task 2 findings may change Tasks 10 and 13, and settle C6. (Done.)
3. **Before anything resumes:** review the YouTube plan and approve the order above.
4. Y0's video leg: up to 15 credits, the unused part of the 40 spike cap, or skip it.
5. Task 15 and 16: owner enters API keys.
6. Before Y8: approve up to 60 credits for Y8 and Y9, proposed inside the 300 cap.
7. Before Task 19: approve up to 300 credits.
