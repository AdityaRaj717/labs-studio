# YouTube Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent turns a moodboard file and a prompts file into reviewed character sheets, stills and silent animations, with per-item approval and regeneration in the app.

**Architecture:** A Production is a Run plus an atomic `production.json`. A pure reducer and `nextItem` scheduler decide everything; a thin orchestrator feeds the engine's existing one-at-a-time queue. The app only displays state and sends actions.

**Tech Stack:** Same as the base plan: Node 22, Playwright over CDP, `node:test`; Python 3.12, PySide6, pytest; FFmpeg.

**Spec:** `docs/superpowers/specs/2026-11-02-youtube-production-design.md`. Base plan: `docs/superpowers/plans/2026-11-02-flow-agent-control.md`. Read the spec and the base plan's Global Constraints, Build Rules and Spike rulings before any task.

**Order (from the base plan):** 1-4 done → **Y0** → 5-8 → 9-11 → **Y1-Y5** → 12-14 → **Y6, Y7** → 15, 16 → **Y8** → 19 → **Y9** → 20 → Phase L.

## Global Constraints

The base plan's all apply. Added:

- UI: only the changes in spec R1. No new page, panel, column, button or colour.
- A production Animation's deliverable has zero audio streams, proven by ffprobe, with no option to turn this off.
- A regeneration changes only its own Item. Files are never overwritten or rewritten.
- The engine never interprets prose beyond exact name match. Judgement comes in through `overrides` or `plan`.
- Spend only inside `max_credits`, with Flow's quote as the gate. No live video outside an owner-approved budget: Y0 at most 15, Y8 and Y9 at most 60 together, each only after the owner agrees.
- `stitch_video` stays unregistered until Phase L.
- Paths: Node files are relative to `mcp/google-flow/`, Python files to the repo root.

## Review Focus

1. **Double-clicked Retry, or an agent repeating a regenerate after a timeout:** one Take, one spend. Test in Y5.
2. **Ingredient chips left from the last Shot in the composer:** the next Shot must not inherit another character. Test in Y3.
3. **A prompt file edited between plan and start:** refused, no spend. Test in Y4.
4. **Owner approves while Chrome is closed, or the engine restarts right after:** the verdict holds. Test in Y5.
5. **A reference regenerated after its Stills were approved:** those Stills, their files and states are untouched, and flagged Stale. Test in Y5.

## Capabilities

| Tasks | Use |
|---|---|
| All coding | `/ponytail` once per session, `superpowers:test-driven-development`, `superpowers:verification-before-completion`; `executor` for tasks, `sonnet-worker` for tests and docs |
| Y0 | `chrome-devtools` MCP, `tools/flow_spike/record.mjs`; controller only |
| Y1-Y5 | `api-and-interface-design`, `backend-reliability`, `error-handling-patterns`, `codebase-design` |
| Y6-Y7 | `impeccable:impeccable` for a critique of the rendered table, `superpowers:systematic-debugging` |
| Y8-Y9 | `superpowers:systematic-debugging`, `domain-modeling` for the glossary, `/code-review` |

---

## Phase Y-A: Find out (after Task 4, before Task 5)

### Task Y0: Reference attachment spike (controller only, live)

**Depends on:** Tasks 2-4 (`record.mjs`, contract). No engine.

**Files:**
- Modify: `docs/flow-ui-findings.md`, `mcp/google-flow/config/ui-contract.json`
- Create: `mcp/google-flow/test/fixtures/snapshots/character-*.txt`, `mcp/google-flow/test/fixtures/snapshots/picker-uploads.txt`, `mcp/google-flow/test/fixtures/snapshots/tile-failed.txt` if seen, `mcp/google-flow/config/production.json`

**Interfaces:**
- Produces: `config/production.json` `{ "referenceMode": "ingredient"|"character", "maxIngredients": {"image": n, "video": n|null} }`, read by Y1 and Y3; `null` if the video leg is skipped; contract keys for any new labels.

Budget: images use quota only, at most 12 on Nano Banana 2.1. Video at most 15 credits and **only if the owner said yes**; otherwise skip Step 4 and note it.

- [ ] **Step 1:** In a new Flow project `y0-<date>` with direct composer, generate one Reference Sheet from the spec's template using `MD_02` from `samples/zombie-bunker/moodboard.md`, plus `MD_01` as a place. Download at 2K.
- [ ] **Step 2:** Upload both with unique names. Generate `IMG_01` and `IMG_04` with them as ingredients. View each: same person? any grid layout copied? Test picker search by exact filename and record whether search finds an upload on a later job. Add ingredients until refused, and record the limit. Check whether chips clear after a job.
- [ ] **Step 3:** Create a Flow Character from the sheet (Upload, then Done). Record the save path with snapshots. Generate the same two Shots with the Character chip in direct mode, and compare by viewing.
- [ ] **Step 4 (owner approved only):** Omni 360p 4s Frames with the uploaded Still by name (4 credits); Omni 360p 4s Ingredients with the sheet (4). ffprobe both. Record chip limits in Ingredients mode.
- [ ] **Step 5:** Apply the spec R4 decision rule, write `config/production.json`, write findings with the credits used and the images' paths. If the rule changes the primary, say so at the top of the findings and in the state file. Commit.

---

## Phase Y-B: Engine (after Task 11)

### Task Y1: Prompt files and dry-run plan

**Depends on:** Task 6 (`validateImage`, `validateVideo`, `estimate`, `checkBudget`), Task 7 (`ErrorCodes`, `toErrorPayload`, class map), Task 8 (`src/shim/tools.js`, pinned list), Y0 (`config/production.json`).

**Files:**
- Create: `src/production/parse.js`, `src/production/plan.js`, `test/production-parse.test.js`, `test/production-plan.test.js`, `test/fixtures/productions/{mixed,scene-table,blocks,two-people,prose,bad}/`
- Modify: `src/utils/errors.js`, `src/shim/tools.js`, `src/engine/server.js`, `test/engine.test.js`

**Interfaces:**
- Produces:
  - `discoverFiles(folder) -> {moodboard, prompts}`, throws `PROMPT_FILE_INVALID`.
  - `parseMoodboard(text, path) -> {title, style, ratio, references:[{id, kind|null, name, prompt, line}], errors, warnings}`.
  - `parseShots(text, path) -> {ratio, shots:[{id, kind, prompt, refs|null, start, end, duration, model, resolution, line_id, line}], errors, warnings}`. `refs: null` means no `Refs` column or field; `[]` means explicit `none`. `start` is an ID, `null` for explicit `none`, or `undefined` when absent.
  - `buildPlan({folder, moodboard_path, prompts_path, plan, overrides, defaults, name}) -> {ok, plan_id, mode, counts, cast, errors, warnings, analysis_needed, implied, estimate}`; `loadPlan(plan_id) -> PlanDoc | throws PLAN_CHANGED`, re-hashing source files. PlanDoc's shape is in spec section 5.
  - Error codes `PROMPT_FILE_INVALID`, `ANALYSIS_REQUIRED`, `PLAN_CHANGED`, `PRODUCTION_NOT_FOUND`, `ITEM_NOT_FOUND`, `REVIEW_CONFLICT`, class Caller fix.
  - Tool `flow_production_plan`, annotated per spec section 11.

- [ ] **Step 1:** Write `test/production-parse.test.js`:
  - `zombie sample parses to 4 references and 8 stills with no errors`, reading `../../samples/zombie-bunker/`; `MD_02` kind `character` name `The narrator`, `MD_01` kind `place`, `MD_04` kind `null`; `IMG_03.refs` is `['MD_02','MD_03']`; ratio `16:9`.
  - `scene table yields S01_IMG and S01_ANI with an explicit start`; `blocks under Characters get CH_ ids`.
  - `escaped pipe stays in the prompt`; `BOM is accepted`; `non-UTF-8 is an error with file and line`.
  - `duplicate ID across both files`, `empty prompt`, `column count mismatch`, `Type conflicting with prefix`, `two different ratio tokens` each give an error with its line.
  - `discovery prefers animation over still, and errors on two equal matches listing both`.
- [ ] **Step 2:** Write `test/production-plan.test.js`:
  - `zombie plan is stills_only, 0 credits, quota 12 on Nano Banana 2.1, no ffmpeg need`; `zombie plan lists MD_04 in analysis_needed until an override sets it to place`.
  - `a mixed plan with ratio 1:1 is an error naming the animation`; `maxIngredients null skips the refs limit`.
  - `mixed plan estimates Omni 720p 6s at 10 each`; `Duration column overrides the default`; `prose duration is ignored`.
  - `ANI_03 pairs with IMG_03 and appears in implied`; `Start none opts out`; `Start naming an Animation is an error`.
  - `unknown ref is an error`; `exact name in the prompt adds a ref with source name`; `no refs and no name match is analysis_needed`; `kind undetermined is analysis_needed`.
  - `overrides split one row into two references and remap Shots` (fixture `two-people`); `an override naming an unknown ID is an error`.
  - `plan JSON goes through the same validator`; `a plan prompt missing from the sources warns`.
  - `refs above maxIngredients is an error`; `Veo Quality with Ingredients is COMBINATION_NOT_SUPPORTED`.
  - `same inputs give the same plan_id`; `an edited file makes loadPlan throw PLAN_CHANGED`.
  - `sheet prompt uses the template for characters, unchanged prompt for places, style appended, sheet_prompt override wins`.
  - In `test/engine.test.js`: `flow_production_plan never touches the page` and pinned list extended.
- [ ] **Step 3:** Run `npm test`; expect failures on missing modules.
- [ ] **Step 4:** Implement per spec section 4. The sheet template lives in `src/production/plan.js`, copied exactly from the spec.
- [ ] **Step 5:** Run `npm test`; expect PASS. Commit.

### Task Y2: Production state

**Depends on:** PlanDoc from Y1; `REVIEW_CONFLICT` from Y1. No browser, no engine.

**Files:**
- Create: `src/production/state.js`, `test/production-state.test.js`

**Interfaces:**
- Produces:
  - `newProduction(planDoc, {id, runId, flowProjectUrl, maxCredits, gates, referenceMode}) -> Production`, shape per spec section 5. `reuse` References start `approved` with a Take.
  - `applyEvent(production, event) -> Production`, pure. Event types: `take_started {item, n, of_take, key, prompt, refs_used, start_used, end_used}`, `take_queued {item, n, job_id}`, `take_done {item, n, file, original, sha256, audio_streams, quoted_credits}`, `take_failed {item, n, code, message, credits_at_risk, file}`, `take_aborted {item, n, code}`, `credits_spent {item, n, credits}`, `reviewed {items:[{id, take}], verdict, actor, note, at}`, `budget_set {max_credits}`, `estimate_set {item, credits}`, `paused {reason, code}`, `resumed`, `cancelled`. An illegal move throws `REVIEW_CONFLICT`.
  - `nextItem(production) -> itemId|null`; `waitingOn(production, itemId) -> ids`; `depsFor(production, itemId) -> {refs_used, start_used, end_used}`, using Approved Takes (or latest finished Takes with the gate off).
  - `staleItems(production) -> [{item, because}]`.
  - `summary(production) -> {status, stages:{reference, still, animation: {total, planned, generating, pending_review, approved, rejected, regenerating, failed}}, credits:{max, spent, planned}, waiting_on, stale, next_action}`. `status` is one of `running, waiting_review, needs_action, paused, cancelled, complete`, per spec section 6.

- [ ] **Step 1:** Write tests:
  - Every row of the spec's state table, one test each, and `approve from planned throws REVIEW_CONFLICT`.
  - `regenerating an approved item keeps approved_take`; `a failed regeneration returns to approved with last_error`; `rejecting the newer take returns to approved`; `approve with take restores an older take, from rejected too`; `approve names exactly its take, not the latest`.
  - `take_aborted returns the item to planned, or to its prior state when regenerating, and the next take is n+1`; `after a stop then resume, nextItem returns the aborted item and its dependents can run`.
  - `gate off skips a rejected take`; `all failed or rejected with nothing runnable is needs_action naming the item`; `estimate_set changes the item's estimate`.
  - `nextItem returns references first, in file order`; `a still waits for its references with the gate on`; `a still proceeds on the latest take with the gate off`; `an animation waits for its start still`; `a ready still beats a ready animation`; `a failed reference blocks only its dependents`; `nothing is returned while paused or cancelled`; `one active item means null`.
  - `stills_only never returns an animation` (a plan with none); `complete only when all items are approved`; `waiting_review when nothing can run and something is pending`.
  - `reviewing one item leaves every other item deep-equal`; `regenerating a reference alone makes nothing stale`; `approving its new take makes approved dependents stale without changing them`; `animation stale when its still's approved take changes`.
  - `credits planned sums unstarted animations only`; `a reuse reference starts approved and generates nothing`.
- [ ] **Step 2:** Run; expect failure. Implement. Run; expect PASS. Commit.

### Task Y3: Compose jobs, attach references, silent deliverable

**Depends on:** Task 9 (`addIngredient`, `src/flow/ingredients.js`, `applySettings`), Task 10 (`runVideoJob`, `verifyVideo`, `stripAudio`, args `start_frame`, `end_frame`, `ingredients`, `silent`), Task 6 (`assetName`), Task 5 (`createRun`), Y0, Y2 (`depsFor`).

**Files:**
- Create: `src/production/compose.js`, `test/production-compose.test.js`, `test/production-attach.test.js`, `test/fake-flow/pages/picker-uploads.html`
- Modify: `src/flow/ingredients.js`, `src/flow/image.js`, `src/flow/video.js`, `src/flow/download.js`, `src/engine/run-folder.js`, `test/fake-flow/server.js`

**Interfaces:**
- Produces:
  - `takeKey(productionId, itemId, n) -> "prod:<id>:<item>:take:<n>"`.
  - `finalPrompt(item, style) -> string`.
  - `composeJob(production, itemId, n, deps) -> jobSpec`: `{kind:'image'|'video', prompt, model, ratio, count:1, download_size, duration, resolution, mode:'frames'|'ingredients', ingredients:[{file}|{character}], start_frame:{file}, end_frame:{file}, silent:true, auto_confirm:true, max_credits:min(item estimate, cap - spent), output:{dir, seq, name:'<prodShort>-<itemId>', version:n}}`. `silent`, `mode`, `start_frame` only for video. `count` always 1.
  - Job option `output` overrides the default naming in `download.js`, still calling `assetName`.
  - `addIngredient(page, {file})` searches `picker.search` for the basename and uploads only if absent. `assertChips(page, expected)` throws `UPLOAD_STALLED` when ready chips differ.
  - `createRun` adds `references/`, `inputs/`.

- [ ] **Step 1:** Write `test/production-compose.test.js`: `sheet job has no ingredients and uses 2K`; `still job lists approved reference files in order`; `animation with a start uses frames and attaches no references`; `animation with no start uses ingredients`; `video job always has silent true`; `filename carries the production short id and take`; `character mode gives character ingredients`.
- [ ] **Step 2:** Write `test/production-attach.test.js` on fake Flow:
  - `an uploaded sheet is found by name on the second job with no second upload` (fake Flow's upload counter).
  - `a missing file in the picker is uploaded`; `a stalled upload retries then fails with no Start click`.
  - Review Focus 2: `chips left by the last job are cleared before the next Shot`; `chip count below refs means no Start click`.
  - `start frame goes on the Start chip by filename`.
  - `the file a production video job reports is the silent copy, not the original`.
- [ ] **Step 3:** Run; expect failure. Implement.
- [ ] **Step 4:** Run `npm test`; expect PASS. Commit.

### Task Y4: Orchestrator, start, status, resume

**Depends on:** Task 5 (`createRun`, `appendEvent`, `writeManifest`, `enqueue`, `recover`), Task 8 (worker, `flow_wait`), Task 7 (`detectBlock`, ledger, `getBalance` per the quote gate ruling), Task 11 (`reconcile`, `flow_job_control`, `flow_create_character`, used only for `reference_mode: character`), Task 3 (`runDoctor`), Y1, Y2, Y3.

**Files:**
- Create: `src/production/store.js`, `src/production/orchestrator.js`, `test/production-run.test.js`
- Modify: `src/engine/worker.js`, `src/engine/server.js`, `src/engine/start.js`, `src/shim/tools.js`, `src/shim/guide.md`, `test/fake-flow/server.js`

**Interfaces:**
- Produces:
  - `loadProduction(run) -> Production`, replaying events past `last_seq`; `commit(run, production, event) -> Production`, append and fsync then atomic rewrite.
  - `createOrchestrator({jobs, store, flow}) -> {start(args), status(args), onJobEvent(ev), recover()}`, extended by Y5. `flow` has `preflight({needsVideo}) -> {balance}`.
  - Tools `flow_production_start`, `flow_production_status`, per spec section 11.
  - Events `production.item`, `production.summary` on `/events`.
  - `flow_wait` on a production's `run_id` adds `production: summary`.
  - `flow_production_status` with `detail:'full'` returns every field of a `production.item` event, for the app mirror.
  - `flow_job_control {action:'resume', run_id, accept_quote:true}` writes `estimate_set` from the observed quote.
  - Fixtures pass the override `MD_04 -> place` wherever they start the zombie sample.

- [ ] **Step 1:** Write `test/production-run.test.js` on fake Flow with its click counter:
  - `stills-only production generates references then stills, with the video setting never touched and no ffmpeg check`.
  - `reuse copies the approved file, records sha256 and generates nothing`; `reuse of an unknown production is PRODUCTION_NOT_FOUND`, `of an unknown item is ITEM_NOT_FOUND`, `of an unapproved item is REVIEW_CONFLICT`; `new_run starts a second production from one plan`.
  - `character mode creates the Flow Character once, before the first dependent, and approval alone never touches the page`.
  - `start with gates on stops at review after references`; `approving through a test helper continues to stills`.
  - `mixed production: an animation starts only after its still is approved`; `its Start chip holds the approved still file`.
  - Refusals, all with zero page use: `start without cast_confirmed`; `start with analysis_needed is ANALYSIS_REQUIRED`; `start without auto_confirm`; `mixed start with no max_credits is INVALID_PARAMS and states the estimate`; `estimate above max_credits is BUDGET_EXCEEDED`; Review Focus 3: `an edited file at start is PLAN_CHANGED`.
  - `doctor failure at preflight stops with UNKNOWN_UI_CHANGE before any Start`; `missing FFmpeg with animations is FFMPEG_NOT_FOUND before any Start`; `estimate above the live balance is BUDGET_EXCEEDED`.
  - `start repeated with the same plan_id returns the same production`.
  - `quota text pauses the production, aborts the unsubmitted take, and planned items stay planned`; `CAPTCHA pauses with needs_user`; `resume through flow_job_control retries the aborted item as a new take, and dependents then run`.
  - `SAFETY_BLOCKED fails one item and others go on`; `a failed reference leaves dependents waiting and others running`; `RESULT_MISMATCH never reaches pending_review and keeps the file`.
  - `an animation doesn't auto-retry a failed generation; an image retries once inside its take`.
  - `a quote above the item estimate stops with quote_drift and no Start click`; `resume with accept_quote then proceeds at the new estimate`; `spent plus quote above max_credits stops with no Start click, and set_budget clears it`.
  - Crash matrix, killing at each row of spec section 7's table then calling `recover()`: `no second Start click` at every point, `a submitted job with a result is downloaded`, `a submitted job with none fails with credits_at_risk`, `strip repeats after a crash with no spend`.
  - `status for 300 items stays under 2,000 tokens`; `status item listing pages with cursor`; `SSE replay after reconnect contains every production.item in order`; `progress source flow only comes from tile text`.
- [ ] **Step 2:** Run; expect failure. Implement. Start copies inputs to `inputs/`, opens or creates the Flow project via the existing tool code, then loops: `nextItem`, record Take, `enqueue` with `takeKey`. Add the workflow to `guide.md` and server `instructions`: plan, answer `analysis_needed`, start, watch with `flow_wait`, tell the owner to review, never approve unasked.
- [ ] **Step 3:** Run `npm test`; expect PASS. Commit.

### Task Y5: Review, regenerate, budget

**Depends on:** Y4; Task 11 (`flow_job_control`); Task 7 ledger.

**Files:**
- Create: `test/production-review.test.js`
- Modify: `src/production/orchestrator.js`, `src/engine/batch.js`, `src/shim/tools.js`, `src/shim/guide.md`, `src/shim/client.js`

**Interfaces:**
- Produces:
  - `orchestrator.review({production_id, items:[{id, take}], action, note, actor}) -> {items:[{id, state, approved_take}], summary, stale}`; idempotent. Atomic: if any Item is illegal, nothing changes, and the error lists which.
  - `orchestrator.regenerate({production_id, item, prompt, expected_take, auto_confirm, dry_run, actor}) -> {take, job_id, state, estimated_credits}`.
  - `orchestrator.setBudget({run_id, max_credits})`, through `flow_job_control {action:'set_budget', run_id, max_credits}`. `retry_failed` on a production run calls `regenerate` per failed Item.
  - Tools `flow_production_review`, `flow_production_regenerate`. The shim forces `actor:'agent'`, and strips any `actor` from agent arguments. The app's RPC passes `actor:'app'`.

- [ ] **Step 1:** Write `test/production-review.test.js`:
  - Review Focus 4: `approve works with no browser connected`; `an approval survives kill and restart`.
  - `batch approve of 3 changes those 3`; `approve with one illegal item changes nothing and names it`; `approving twice is a no-op`.
  - `retry with no prompt makes take 2 with the same prompt`; `modify makes take 2 with the new prompt and leaves the source file and take 1 unchanged`.
  - Isolation: `regenerating IMG_05 leaves every other item's state, takes, and file sha256 identical`; `regenerating an item leaves its v1 file on disk`.
  - Review Focus 5: `regenerating an approved reference and approving the new take flags its approved stills stale and changes nothing else`.
  - Review Focus 1: `the same regenerate repeated during regenerating, with the same expected_take, returns the running take`; `a different prompt during regenerating is REVIEW_CONFLICT`; `a stale expected_take when idle is REVIEW_CONFLICT with the current take`; `a double call produces one Start click`.
  - `an image regeneration needs no max_credits`; `an animation regeneration above remaining minus planned is BUDGET_EXCEEDED with the amount`; `dry_run returns the cost with no job`; `no auto_confirm spends nothing`; `set_budget raises the cap and is journaled`.
  - `retry_failed regenerates only failed items within budget`.
  - `a regenerated reference's job attaches the Approved Take of its deps at that time`; `regenerated take waits for review`.
  - `agent-supplied actor is overwritten with agent`; `each verdict records actor and time`.
  - `the concise review reply stays under 500 tokens for 30 items`.
- [ ] **Step 2:** Run; expect failure. Implement. Run `npm test`; expect PASS.
- [ ] **Step 3:** T3 live, images only, no credits: `samples/zombie-bunker/` with the first two References and `IMG_01`: plan, start, approve, regenerate `IMG_01`, confirm the file set by viewing. Quota only. Commit.

---

## Phase Y-C: App (after Task 14)

### Task Y6: Production rows in the table

**Depends on:** Task 13 (`EngineClient`, `Job.preview`), Task 14 (`RunMirror`, `origin`), Y4 events.

**Files:**
- Create: `tests/test_production_rows.py`
- Modify: `src/gen/models.py`, `src/projects/store.py`, `src/web/run_mirror.py`, `src/ui/generator/prompt_model.py`, `src/ui/generator/prompt_table.py`, `src/ui/generator/page.py`, `src/languages/en.py`

**Interfaces:**
- Produces:
  - `Job` fields, all defaulted: `production_id: str`, `item_id: str`, `review: str`, `take: int`, `stale: str`, `ref_labels: list[str]`. Round-trip in `job_to_row` and `row_to_job`; a production row loaded as `QUEUED` or `RUNNING` isn't forced to `STOPPED`, since the mirror refreshes it from the engine.
  - `RunMirror.apply_production_event(event)`, mapping per the spec section 12 table: References and Stills to `flow_image`, Animations to `flow_video`, exactly one row per Item. `RunMirror.start` calls `flow_production_status` with `detail:'full'` per production run, and feeds each item through this.
  - `banner_text(summary, name) -> str`, a module function in `src/web/run_mirror.py`; `GeneratorPage.set_production_summary(summary, name)` writes it in `banner_label` beside any provider banner.
  - `status_color(job) -> str` in `prompt_model.py`, used by the Status cell and `ProgressDelegate`.
  - Strings: `review_pending_review` ("Review v{take}"), `review_approved` ("Approved v{take}"), `review_rejected` ("Rejected"), `review_regenerating` ("Regenerating").

- [ ] **Step 1:** Write tests with a fake engine:
  - `one event per state gives one row, with the mapped JobStatus`; `references and stills land on flow_image, animations on flow_video`.
  - `status text for review and approved includes the take`; `colours come only from STATUS_COLORS values`; `a rejected row's progress bar uses the rejected colour`.
  - `prompt cell shows IMG_01 and the prompt; EditRole returns the prompt alone`; `a production prompt cell isn't editable, a normal row still is`.
  - `character cell shows the Cast names`; `tooltip names the stale cause`.
  - `Start never submits a production row`; `Clear keeps production rows and removes others`; `stats counts include production rows`.
  - `rows round-trip through project.json`; `closed-app production rebuilds rows on reopen with review state`.
  - `banner shows counts, credits and waiting for your review`; `paused reason appears in the banner`.
  - `the output cell for an animation is the silent file`.
  - `column count and keys are unchanged`.
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest -q tests/test_production_rows.py`; expect failure. Implement. Run the whole suite; expect PASS. Commit.

### Task Y7: Review controls

**Depends on:** Y5 tools, Y6 rows, Task 13 (`EngineClient.call`).

**Files:**
- Create: `src/web/production_actions.py`, `tests/test_review_controls.py`
- Modify: `src/ui/generator/prompt_table.py`, `src/ui/generator/page.py`, `src/languages/en.py`

**Interfaces:**
- Produces:
  - `ProductionActions(client)`: `.approve(jobs)`, `.reject(jobs)`, `.regenerate(job, prompt=None, dry_run=False) -> dict`, `.raise_budget(run_id, max_credits)`. Calls pass `actor:'app'`; `approve` and `reject` send `{id, take}` from `job.take`; `regenerate` sends `expected_take` and `auto_confirm:true`, since the owner's click is the confirmation. Qt-free, off the GUI thread by the page's existing thread and signal pattern. Errors become `ActionError(code, message, details)`.
  - `PromptTable` signals `approve_requested(list)`, `reject_requested(list)`, `regenerate_requested(list)`.
  - `GeneratorPage.approve_rows`, `.reject_rows`, and `retry_rows`, `edit_row`, `retry_failed` routing rows with `production_id` to `ProductionActions`, others unchanged.
  - Strings: `gen_approve`, `gen_reject`, `gen_retry_same`, `gen_modify_regen`, `gen_regen_cost`, `gen_regen_raise`, `gen_engine_error`.

- [ ] **Step 1:** Write tests with a fake client:
  - Menu: `a production row offers Approve, Reject, Retry with same prompt, Modify; Remove disabled; character and scene menus hidden`; `a normal row's menu is unchanged`; `Approve is enabled only with a pending_review row selected`.
  - `Ctrl+Return approves selected rows`; `multi-select approve sends all IDs in one call`; `Modify is single-row`.
  - `Retry on a mixed selection routes production rows to regenerate and others to the queue`; `Retry failed does the same`.
  - `Modify opens the raw prompt without style, and on OK calls regenerate with the new text and expected_take`; `Cancel sends nothing`; `an unchanged prompt on OK acts as Retry`.
  - `Regenerating an animation shows the cost from dry_run first; No sends nothing`; `over budget offers to raise and retries once on Yes`; `an image regeneration shows no box`.
  - `REVIEW_CONFLICT refreshes the row and shows the message`; `engine down shows the message and doesn't change the row`; `no action blocks the GUI thread` (fake client with a delay).
  - `the row changes only on the engine's event, not on click`.
- [ ] **Step 2:** Run; expect failure. Implement. Run the whole suite; expect PASS.
- [ ] **Step 3:** Render both pages at light and dark with a fake production via `tools/make_help_screenshots.py`. View them against the Task 14 layout screenshots. Expected: same layout; `Regenerating` fits the 100px status cell. Run `impeccable:impeccable` critique on the rendered result, and fix only within R1. Commit.

---

## Phase Y-D: Proof (after Task 16)

### Task Y8: Live acceptance (owner checkpoint: at most 60 credits together with Y9, inside the 300 cap)

**Depends on:** Y1-Y7, Tasks 15, 16. Not to run without the owner's approval of the budget.

**Files:**
- Create: `tests/live/run_production.mjs`, `docs/production-live-acceptance.md`, `samples/zombie-bunker-animated/` (a copy of the moodboard plus one `image-and-animation-prompts.md` holding the `IMG_` rows and new rows `ANI_01` to `ANI_03` paired by number, `ANI_04` with `Start: none` and refs, `ANI_05` at 720p with its own still, `ANI_06` for the crash check; `samples/zombie-bunker/` stays stills-only)

Budget plan, Omni unless stated, stopping at 35:

| Check | Credits |
|---|---|
| 3 Frames animations 360p 4s from approved stills | 12 |
| 1 Ingredients animation 360p 4s | 4 |
| 1 Omni 720p 4s | 7 |
| Modify one animation and retry one, 360p 4s | 8 |
| Crash right after Start, one 360p 4s | 4 |

- [ ] **Step 1:** Stills-only live: all of `samples/zombie-bunker/` unchanged, with the override `MD_04 -> place`. Expected: 4 references, 8 stills, no video job, no credit change on the account panel. View the contact sheet; owner reviews in the app.
- [ ] **Step 2:** Mixed live with `max_credits: 35` on `samples/zombie-bunker-animated/`. Compare the app's rows and banner against Chrome at each stage. Exercise the app's Approve, Retry and Modify by hand.
- [ ] **Step 3:** Prove silence: for each Animation, ffprobe on the deliverable shows zero audio streams and on `_original` shows one. Save the output in the evidence file. Prove isolation: sha256 of all other files is unchanged before and after both regenerations.
- [ ] **Step 4:** Kill the engine right after a Start click, and restart. Expected: no second spend, by balance. Close Chrome mid-run. Expected: clear failure, resumable.
- [ ] **Step 5:** Record credits by balance against the ledger. Report any failure plainly, and fix with a failing test first. Commit.

### Task Y9: Cold-agent evals, docs

**Depends on:** Y8, Y4's `src/shim/guide.md`. Runs before Task 20, whose eval harness (`tests/evals/score.mjs`) it creates early and Task 20 extends.

**Files:**
- Create: `tests/evals/production_prompts.json`, `tests/evals/score.mjs`, `tests/evals/fixtures/*`
- Modify: `src/shim/guide.md`, `src/shim/tools.js`, `help/en/mcp-agents.md`, `mcp/google-flow/README.md`

- [ ] **Step 1:** Write the spec section 12 evals, each with a fresh `sonnet-worker` given only the MCP and a folder. Score completion, tool calls, wrong calls, unapproved spend, self-approval.
- [ ] **Step 2:** Run on fake Flow first, then the two that need it live: at most 25 credits remaining of the 60.
- [ ] **Step 3:** Fix descriptions, errors and the guide, not the prompts. Target per spec. Document the prompt-file format and the workflow in help. Commit.

---

## Later: Phase L (not scheduled; owner's word)

- **L1:** base Task 18 stitcher, `stitch_video`, `last_frame` tool, `pythonPath`. Consumes silent deliverables and Approved Takes.
- **L2:** voice selection, testing, base Task 16's character voice row and `preview_voice`.
- **L3:** audio editing, SFX placement, sync, final assembly; base Task 19's stitch and music tests; base Task 20's assembled-video eval.
- Optional: base Task 17.

## Owner checkpoints

1. Before anything resumes: approve the order.
2. Y0 Step 4: up to 15 credits, or skip.
3. Before Y8: up to 60 credits inside the 300 cap.
4. Tasks 15, 16: API keys.
5. Before Y1, if available: a real prompts file.
