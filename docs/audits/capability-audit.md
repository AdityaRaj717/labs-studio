# Capability audit: Flow engine / MCP vs the Labs Studio app

Read-only audit of D:\Prog\labs-studio-dev, working tree as of 2026-11-03 (uncommitted Contact Sheet UI included). `graft` is not on the Bash PATH here, so I used Read/Grep/sed only. Nothing was run against Chrome, Flow, or the engine.

Paths are relative to the repo root. Engine = `mcp/google-flow/src` (abbrev. `E/`). Client = `src/web` and `src/gen`. "UI" = `src/ui`.

Status legend: FULL = reachable and usable from the app UI; PARTIAL = reachable but a part of the engine's surface or data is hidden; READ-ONLY = the app only displays it; MISSING = no app path at all (agents only).

---

## 0. How the app reaches the engine (the surfaces that exist)

HTTP, loopback, bearer token, `E/engine/server.js`:

| Route | Entry | Python | Use |
|---|---|---|---|
| `GET /events` (SSE, replay by `since`, 15 s ping, `reset` on restart) | server.js:107, 85-103 | `EngineClient.events` engine_client.py:155 | RunMirror (run_mirror.py:115) and per-job follow (flow_mcp.py:204-208) |
| `GET /health` (`ok, ready, version, pid, uptimeMs, seq, worker{paused,active}`) | server.js:108-110 | `EngineClient._health` engine_client.py:68, `head()` :127 (reads only `seq`) | `worker.paused` and `uptimeMs` are never read by the app |
| `POST /rpc {tool,args}` | server.js:111-118 | `EngineClient.call` engine_client.py:132 | every tool call |
| `POST /secrets` (FISH_API_KEY, STABILITY_API_KEY) | server.js:119-128 | `src/keys_push.py` `_post`, `pushKeys`, `forgetKey` | Settings, API keys (settings_page.py:28-40, KeyRow) |
| `POST /shutdown` (409 while a job runs) | server.js:129-134 | NONE (grep for "shutdown" in src/web: none) | no UI |

Files the app reads without the engine (engine_client.py): `runs.jsonl` + each `manifest.json` (`read_manifests` :189), `pacer.json` (`uses_today` :216), and `production.json` (run_mirror.py:129). `ledger.json` (balance, per-job spends) is NOT read by the app at all (grep "ledger.json" in src: none).

RPC tool set = the 38 tools in `E/shim/tools.js` plus two app-only tools `flow_bring_to_front`, `flow_set_pacing` (rpc.js:34, handlers :324, :336). `known` set at rpc.js:350.

---

## A. Capability table

| # | Capability | Engine / MCP entry | Python client wrapper | App UI | Status | Gap | Engine already exposes data? |
|---|---|---|---|---|---|---|---|
| **Connection, health, session** | | | | | | | |
| A1 | Launch/attach Chrome, open Flow, check account | `flow_connect` tools.js:37, rpc.js:242-246, 298 | `BrowserSession.login_state/open_site` session.py:23,28 | Settings > Web Sessions "Launch/Check" buttons web_sessions_tab.py:70-72, `do_action` :186-195 | FULL | Only on a settings tab; the Contact Sheet shows no connection state. | yes |
| A2 | Disconnect (detach Chrome) | `flow_disconnect` tools.js:40, rpc.js:298-301 | NONE | NONE | MISSING | No way to detach from the app. Low value. | yes |
| A3 | Bring Chrome tab to front | `flow_bring_to_front` (app-only) rpc.js:324-335 | `bring_to_front` session.py:34; also called on blocks `map_engine_error` web_flow_image.py:54 | auto on block/UI-change only; Launch button | PARTIAL | No "Show in Flow" button on a running frame/take. | yes |
| A4 | Engine status: browser, account, page, active job, queue counts, ledger (month total, per-model daily image quota), balance | `flow_status` tools.js:41, rpc.js:234-240, `handleFlowStatus` tools/flow-status.js:42-91 | `FlowMcp.status` flow_mcp.py:245 | NONE. grep `\.status()` in src/ui finds no caller. | MISSING (client exists, unreachable) | No balance, month credits, or daily image quota anywhere in the UI. | yes (`balance` from ledger.json, throttled live read 60 s; `ledger.monthTotal`, `ledger.todayQuota[model]`) |
| A5 | Doctor: Flow page vs UI contract | `flow_doctor` tools.js:44, rpc.js:303 | called in `diagnose()` diagnose.py:27 | Settings > Web Sessions "Diagnose" btn web_sessions_tab.py:72, :192-194 (saves a report file and opens it) | PARTIAL | A report file, no inline pass/fail. Engine also runs doctor automatically at Production preflight (rpc.js:256). | yes |
| A6 | Screenshot of Flow tab | `flow_screenshot` tools.js:214, rpc.js:343 | diagnose.py:28 only | inside Diagnose report | PARTIAL | No "see what Flow shows now" button. | yes |
| A7 | Engine health: uptime, ready, `worker.paused` reason, `worker.active` | `GET /health` server.js:108-110 | `_health` engine_client.py:68 (only `seq` used) | NONE | MISSING | A paused queue (WAF_BLOCK, DAILY_CAP, owner/verification stops) is invisible unless the app's own job is waiting. | yes |
| A8 | Capabilities: models, ratios, counts, sizes, per-model credit table, limits, verifiedAt | `flow_capabilities` tools.js:45, rpc.js:304; file `config/capabilities.json` | `capabilities()` web_flow_image.py:46 reads the JSON file directly (not via RPC) | builds choice lists: web_flow_image.py:151-153, web_flow_video.py:37-38 | PARTIAL | Only model/ratio/size/default come from caps. Duration list is hard-coded `["4","6","8","10"]` (web_flow_video.py:39) so Veo shows durations it cannot make (caps say Veo = 8 only; `quote()` web_flow_video.py:13-25 then fails at run time). `limits` (daily image quota, monthly credits, 50 bonus) never shown. Count spinner allows 8 (config_panel.py:21) but engine accepts 1-4 and the provider clamps silently (web_flow_image.py:167, web_flow_video.py:48). | yes |
| A9 | Pacing: daily cap, min/max gap | `flow_set_pacing` (app-only) rpc.js:336-342; `pacer.json` | `push_pacing` flow_mcp.py:109; `uses_today` engine_client.py:216 | Settings > Web Sessions: cap spin, "used today / cap" web_sessions_tab.py:92-100 | FULL | Not on the sheet. Raising the cap frees a cap-stopped queue (rpc.js:340) but no other queue pause has a resume control (see C. runs). | yes |
| **Generation (single jobs)** | | | | | | | |
| A10 | Image job: prompt, model, ratio, count 1-4, size 1K/2K | `flow_generate_image` tools.js:50, rpc.js:305 via `queueGeneration` :152-165; `validateImage` engine/validate.js:50 | `WebFlowImageProvider.generate` web_flow_image.py:158-172; `run_engine_job` :93; `FlowMcp.run_job/_follow` flow_mcp.py:158,195 | Inspector > Settings (ConfigPanel config_panel.py:20-30 plus provider fields web_flow_image.py:151-154) built at page.py:101; queue via Start page.py:771 | FULL | `max_generation_retries` (engine auto-retries failed image tiles, default 1, each try spends quota) is never passed or shown; the app also has its own `max_retries` (config_panel.py:25), so a failure can be retried at two layers. `job.attempt` from `jobView` rpc.js:56 is ignored. | yes |
| A11 | Video job: model, ratio, duration, resolution, count, silent | `flow_generate_video` tools.js:60, `validateVideo` validate.js:78-98 | `WebFlowVideoProvider.generate` web_flow_video.py:45-57 | Settings fields web_flow_video.py:37-42 | FULL for text and ingredients | Cost: local `quote()` runs per job at run time and `max_credits = cost*count` per job (web_flow_video.py:50-54): there is no pre-Start batch total and no run-wide cap for app-started batches. | yes |
| A12 | Video Frames mode: `start_frame`, `end_frame` | tools.js:68-69, engine flow/video.js:attachMore, ingredients.js `addFrame` | NONE: app sends refs only as `ingredients` (web_flow_video.py:52-55) | NONE | MISSING | A producer cannot say "this still is the first frame" from the sheet. (Productions do it internally: production/compose.js.) | yes |
| A13 | Video Extend (`extend_from`) / Edit (`edit_from`) | tools.js:70-71, flow/clip.js:extend/edit, caps `modes` (capabilities.json) | NONE | NONE | MISSING | No extend/edit of a take. | yes |
| A14 | Estimate credits/quota (free) | `flow_estimate` tools.js:47, rpc.js:264-267 | NONE (the app uses its own `quote()` web_flow_video.py:13) | Regenerate-cost dialog only uses `estimated_credits` from regenerate dry run (page.py:688-691) | MISSING | No "this batch costs N credits" before Start. | yes |
| A15 | Dry run = no `auto_confirm` | rpc.js:159 | app always sends `auto_confirm: True` flow_mcp.py:172 | NONE | n/a | n/a | n/a |
| A16 | Reference images as ingredients (file paths) | `ingredients` schema tools.js:20-24; `checkIngredients` validate.js:24-33; Flow picker flow/ingredients.js | `refs` -> `ingredients` web_flow_image.py:157-169 | Import/paste/drop (page.py:533-552), folder `ref_dir` auto-match `match_refs` page.py:554, Refs column + Take panel "References" take_panel.py:71,139 | FULL | Image ingredient cap is 16, video unknown (config/production.json); no UI warning. | yes (`maxIngredients`) |
| A17 | Characters / scenes as ingredients by name | ingredient `{character|scene}` ; `flow_create_character` etc. | `FlowSync.names/ensure` (src/characters/flow_sync.py:55-130), `run_job` flow_mcp.py:176-181 | Characters/Scenes pages; Cast/Scene columns & Take panel take_panel.py:69-70; `set_character` page.py:572 | FULL | n/a | yes |
| A18 | Idempotency key (a repeat returns the first job, no second spend) | tools.js:15, rpc.js:155 | `job.engine_key = app:<uuid>` web_flow_image.py:97 | invisible by design | FULL | n/a | yes |
| A19 | Batch queue from JSON/CSV with `stop_on` | `flow_batch_start` tools.js:75, rpc.js:281-285, engine/batch.js | NONE (grep `flow_batch_start` in src: none) | NONE; the app queues its own per-job calls | MISSING | Agent batches work (RunMirror shows them) but the app cannot make one and so never uses `stop_on`, run-level `max_credits`, or run names. | yes |
| A20 | Job/run status | `flow_job_status` tools.js:132, rpc.js:116-124 (concise or full; paged 50) | `flow_wait` used instead (flow_mcp.py:216) | per-row status/percent | PARTIAL | `jobView` fields are never shown beyond `state`, `outputs`, `error`, `progress` (see section B). | yes |
| A21 | Wait for job/run | `flow_wait` tools.js:137, rpc.js:126-150 | flow_mcp.py:216 (2 s slices, WAIT_MS :30) | n/a | FULL | n/a | yes |
| A22 | List recent runs with job counts | `flow_list_runs` tools.js:147, rpc.js:310 | NONE; the app reads `runs.jsonl` + manifests directly (`read_manifests`) | Agent runs appear as rows (RunMirror.refresh run_mirror.py:208) | PARTIAL | No run list/history view; run name and run folder not shown; only rows. | yes |
| **Run control** | | | | | | | |
| A23 | Cancel a job | `flow_job_control cancel` rpc.js:216-222 | `_follow` flow_mcp.py:214,224 | Stop button page.py:820 -> `queue.stop` -> `should_stop` -> cancel | PARTIAL | Stop is whole-queue; no per-take cancel; an agent's job cannot be cancelled from the app (the app only controls rows it queued). | yes |
| A24 | Pause / resume a queue or run | `flow_job_control pause/resume` rpc.js:194-213, 203-205 | NONE. App Pause (page.py:813) pauses only the in-app `JobQueue`, never calls `flow_job_control`. | Pause button | PARTIAL (name lies) | Pausing the app does not pause an engine run or a Production; and an engine-paused queue (WAF_BLOCK, verification, quota) cannot be resumed from the app. (Production-live-acceptance: "raising the daily cap left the queue stopped with no app control", fixed only for DAILY_CAP via flow_set_pacing.) | yes (`/health.worker.paused`, `queue_paused` in `flow_wait`, `flow_job_control resume`) |
| A25 | Retry failed (may spend) | `flow_job_control retry_failed` rpc.js:223-227 (+ Production variant :188) | NONE; the app re-submits as a new job (`_retry` page.py:799) or Production regenerate | Retry button page.py:795, sheet `R` key, confirm dialog `_confirm_retry` page.py:486 | PARTIAL | Works but via a new job; failed Production items retry through regenerate (page.py:710). | yes |
| A26 | `set_budget` (raise a Production cap) | rpc.js:183-187, orchestrator.js:403 | `raise_budget` production_actions.py:55 | Only inside the regenerate over-budget dialog (page.py:694-708) | PARTIAL | No standalone "raise cap" control or visible cap/remaining. | yes (`credits.max/spent/planned` in summary) |
| A27 | `accept_quote` on resume of a quote-drift stop | tools.js:145, rpc.js:204 | NONE | NONE | MISSING | Banner says "paused: quote drift" (run_mirror.py:51-53) but there is no button to accept it. | yes (`paused.reason`, `paused.quoted`, `paused.item` in summary) |
| **Productions** | | | | | | | |
| A28 | Plan a Production (dry run: parse files, cast, shots, estimate, eta) | `flow_production_plan` tools.js:88, `buildPlan` production/plan.js | NONE (grep `flow_production_plan`/`start` in src: none) | NONE | MISSING | A Production can only be started by an agent. The app only reviews them. | yes |
| A29 | Start a Production (gates, reference_mode, max_credits, new_run) | `flow_production_start` tools.js:97, orchestrator.js:249-293 | NONE | NONE | MISSING | Same. Gates (references/stills review on or off) cannot be set from the app. | yes |
| A30 | Production status: per-stage counts, credits, paused reason, next_action, waiting_on, stale; items paged | `flow_production_status` tools.js:108, orchestrator.js:294-306, `summary` state.js:298 | `_read_production` run_mirror.py:141; `current` production_actions.py:58 | Banner line: `banner_text` run_mirror.py:39-56, shown in `run_notice` page.py:167,349-357 | PARTIAL | `next_action`, `waiting_on`, `stale` list and `credits.planned` are not shown; the banner is one text line. | yes |
| A31 | Items (Reference/Still/Animation) with state, take, approved_take, prompt, file, ref names, stale, error | itemView orchestrator.js:52-73 | `item_fields` run_mirror.py:59-80 | One sheet frame / table row per Item: Sheet, edge strip sheet.py:222-250, Take panel take_panel.py:119-160 | FULL | Stage (reference/still/animation) is only used to choose the image vs video page (run_mirror.py:159); References and Stills are not grouped on the sheet. | yes |
| A32 | Takes: full take history per item (`takes[]`: n, of_take, prompt, refs_used, start_used, end_used, status, file, original, sha256, audio_streams, quoted_credits, credits_at_risk, verdict, actor, at, note) | `flow_production_status detail:full` -> `takes: item.takes` orchestrator.js:302; shape state.js:97-100 | read but dropped: `item_fields` keeps only latest take number and one `file` (run_mirror.py:71-75) | Take number appears in the status text "approved (take 2)" (en.py review_*) only | READ-ONLY (number only) | No take history strip, no compare of take 1 vs 2, no per-take credits, prompt used, refs used, or "who approved". Earlier takes stay on disk but are unreachable from the UI. | yes (already fetched with detail=full, then discarded) |
| A33 | Approve / reject named Takes (all-or-nothing, actor app) | `flow_production_review` tools.js:117, orchestrator.js:347-365 | `approve/reject` production_actions.py:40-44 | Sheet P/X keys, Ctrl+Enter, Take panel buttons take_panel.py:49-53, viewer, context menu; page.py:669-681 | FULL | Local stills (non-Production) get an app-only mark, not a Flow-side verdict. No `note` field in the UI (engine accepts `note`). | yes |
| A34 | Regenerate an Item (own prompt, dry run cost, expected_take safety) | `flow_production_regenerate` tools.js:123, orchestrator.js:371-401 | production_actions.py:46 | Retry / Edit (E) -> `_regenerate` page.py:682-713, `edit_row` :715 | FULL | Animation shows a cost dialog; stills do not (quota only). No "estimated credits" shown for the whole queue. | yes |
| A35 | Production-level pause / resume / cancel | `flow_job_control` with run_id: `orchestrator.hold/resume/cancel` rpc.js:202-206 | NONE | NONE | MISSING | Verified live by an agent (production-live-acceptance.md "Production pause, resume, cancel PASS") but the owner has no control. | yes |
| A36 | Production retry_failed (current prompts, within cap) | rpc.js:188-193, orchestrator.js:413-428 | NONE (app loops `regenerate` per failed row, page.py:710-713,795) | Retry failed button | PARTIAL | n/a (equivalent) | yes |
| A37 | Stale items (dependency's Approved Take changed) | `staleItems` state.js:260, `stale` in itemView | `item_fields["stale"]` run_mirror.py:73 | Status tooltip only (prompt_model.py review_stale tooltip ~150) | READ-ONLY | Not a badge on the frame; not a filter. | yes |
| A38 | Reuse approved item from another Production (`reuse`) | plan overrides, `resolveReuse` orchestrator.js:222 | NONE | NONE | MISSING | n/a (belongs to plan UI). | yes |
| **Ledger, credits, quota** | | | | | | | |
| A39 | Month credit total, per-job spend by attempt, balance (Flow's own number), quotas | `ledger.js` (recordSpend :43, monthTotal :54, todayQuota :60, recordBalance :32); `getBalance` flow-status.js:16 | NONE | Production banner "N of M credits" run_mirror.py:48-49; regenerate dialogs; Web Sessions "used today" counts prompts, not credits | READ-ONLY (partial) | Nothing shows the real Flow balance, the credits spent by an app batch, or the image quota left per model. | yes in `flow_status` and `ledger.json`; the `Resets <date>` text in the account panel is not captured (docs/flow-ui-findings.md "Balance") |
| A40 | Per-take credits actually spent | take `quoted_credits`, `credits_at_risk` state.js:97-129 | dropped (see A32) | NONE | MISSING | n/a | yes in `takes[]` |
| **Assets, downloads** | | | | | | | |
| A41 | List assets of a run or Flow project | `flow_list_assets` tools.js:149, rpc.js:286-290 (project listing sees only the newest 28 tiles) | NONE | NONE | MISSING | App shows only files from jobs it knows. | yes |
| A42 | Re-download an asset / latest | `flow_download` tools.js:150, rpc.js:291-296 | NONE | NONE (the app saves from the file the job returned) | MISSING | A lost or deleted file cannot be re-fetched from the sheet. | yes |
| A43 | Open output / folder | n/a (files on disk) | n/a | take_panel.py:60 "Open file", `open_output` page.py:869, `open_row_folder` :874, `open_output_folder` :879 | FULL | Video is not played inline; viewer says "Video plays in your default player" (en.py gen_viewer_video) and the sheet shows a play glyph plus filename (sheet.py:175-183). No video thumbnail/poster. | n/a |
| A44 | Last frame of a finished video (for chaining) | `last_frame` tools.js:209, stitch.js:84-92 | NONE | NONE | MISSING | "Use last frame as next start" is the producer's chaining move and it is absent. | yes |
| **Flow projects** | | | | | | | |
| A45 | Open or create a Flow project (and set its title) | `flow_open_project` tools.js:152, open-project.js:112-137 | `open_project`, `ensure_project`, `open_project_async` flow_mcp.py:135,142,261 | Switching/renaming an app project opens/renames it (app.py:76-82), Projects page shows the Flow URL (projects/page.py:101) | PARTIAL | No visible link/state ("Flow project open: yes/no"), no "Open in Flow" button. | yes |
| A46 | List Flow projects | `flow_list_projects` tools.js:155, open-project.js | NONE | NONE | MISSING | Cannot bind an app project to an existing Flow project from a list. | yes |
| A47 | Rename Flow project | `flow_rename_project` tools.js:156 | NONE directly (rename happens implicitly through `open_project(name=...)` -> `setTitle`, open-project.js:130) | implicit on app rename | PARTIAL | n/a | yes |
| A48 | Delete Flow project (confirm:true, permanent) | `flow_delete_project` tools.js:157, rpc.js:314-317 | NONE | NONE | MISSING (deliberate) | Fine to keep agent-only. | yes |
| **Characters and scenes** | | | | | | | |
| A49 | Create character / scene (image free; prompt-only spends) | `flow_create_character`, `flow_create_scene` tools.js:161,166 | `FlowSync._create` flow_sync.py:93-98 | Characters/Scenes pages "Set up in Flow" btn (characters/page.py:151, `_flow_setup` :46) | FULL | Known open bug: a prompt-less create can leave "Untitled character" (docs/flow-live-acceptance.md). | yes |
| A50 | Import character from another project | `flow_import_character` tools.js:163 | `FlowSync._import` flow_sync.py:68-81 | automatic inside Set up | FULL | n/a | yes |
| A51 | List characters (names; details kind/info/url) | `flow_list_characters` tools.js:162 | `FlowSync.verify` flow_sync.py:104-118 (names only) | drops stale links silently; Characters page shows "here / other projects" (characters/page.py:243-247) | PARTIAL | No view of what exists in Flow itself. | yes |
| A52 | List scenes | `flow_list_scenes` tools.js:167 | NONE | NONE | MISSING | Low value. | yes |
| **Audio and stitch** | | | | | | | |
| A53 | Voice (Fish Audio) generate | `audio_voice_generate` tools.js:169, audio/fish.js | keys only (keys_push.py); NO generate wrapper | API-key field in Settings only (settings_page.py KEY_PROVIDERS :24) | MISSING | The app stores the key but cannot make a voice line. Free model `s2.1-pro-free`. | yes |
| A54 | Voice list | `audio_voice_list` tools.js:184 | NONE | NONE | MISSING | n/a | yes |
| A55 | Music / SFX (Stable Audio 3, 8 Stability credits each) | `audio_stable_generate` tools.js:189, audio/stable.js | NONE | key only | MISSING | n/a | yes |
| A56 | Stitch a run into one video (clips, voice, bgm, sfx, transition, loudness) | `stitch_video` tools.js:203, engine/stitch.js:66-83 (emits `job.progress {stage:'stitch', source:'phase'}` :77) | NONE (the app has its own editor stitcher: src/stitch_cli.py, src/editor/stitch.py, not wired to the Flow sheet) | NONE on the sheet | MISSING | "Assemble approved takes in order" is the natural last step of a batch review and has no button. Engine `autoSpec` orders a run's videos and adds voice and music. | yes |
| **Misc** | | | | | | | |
| A57 | Secrets push | `POST /secrets` | keys_push.py | Settings | FULL | n/a | yes |
| A58 | Engine shutdown | `POST /shutdown` | NONE | NONE | MISSING (deliberate) | n/a | yes |
| A59 | Webhook/HTTP API of the app | src/webhook/server.py | n/a | Webhook page | n/a (reports the app's own queue: progress from `job.progress`, webhook/backend.py:35) | n/a | n/a |

Engine pieces that exist in code but are not driven by any tool (so cannot be a parity item): `pageSettings.*` (Sound on hover, Return silent videos, Show tile details, Clear prompt on submit) are only entries in `config/ui-contract.json`; no `src/` file under `E/` references them (grep for `pageSettings`, `returnSilent` returns nothing). `project.swapFrames`, `picker.tab.voices/avatars/videos`, tile menu items beyond Download are also unused.

README caveat: `mcp/google-flow/README.md` is stale. It lists `flow_account_check`, `flow_download_latest`, `flow_open_tools_gallery`, `flow_use_tool`, `flow_use_grid_architect`, `flow_queue_status` and "Imagen 4"; none exist in `E/shim/tools.js`. docs/flow-ui-findings.md ("Tools: ... Grid Architect isn't reachable, which settles C6: removed") confirms Grid Architect is gone. The README's own architecture note (added in the working tree) says "Some sections below describe the older single-process design."

---

## B. Real progress and sync

### B1. Where progress comes from (engine)

1. The only real percent is Flow's own tile text. `observeGeneration` (E/flow/observe.js:61-131) polls every 1 s (`POLL_MS` :7), finds running tiles (`!mediaId && PERCENT.test(text)`, :88), and takes `running[0]` (:97), the first running tile's percent only. When count is 2-4 it is the first tile, not an average or a min. It calls `onUpdate({progress, source:'flow', previewPath?})` only when the percent changes or a preview was saved (:103-106).
2. Image and video generation (E/flow/image.js:137-143) turn that into `job.progress = update` and emit `{type:'job.progress', runId, jobId, progress, source:'flow', previewPath?}`.
3. Video Edit (E/flow/clip.js:100-111) reads `n%` from the clip page and emits the same event with `source:'flow'`. Video Extend has no percent on the page (docs/flow-ui-findings.md: "No percent text was seen"; completion = new timeline clip thumbnail strip appears), so Extend emits nothing.
4. `flow_job_status` / `flow_wait` (rpc.js:52-61 `jobView`): `progress` is `job.progress` only while `state === 'generating'` and a progress object exists, otherwise `{source:'phase', stage:<state>}`. The comment says it plainly: "Flow's own number while it shows one, otherwise only the engine's stage."
5. Stitch emits `job.progress {stage:'stitch', progress, source:'phase'}` with no `jobId` (E/engine/stitch.js:77); the app ignores it.
6. Production items: `itemView` sets `progress: null, source: 'phase'` by default (orchestrator.js:69-70) and `onJobEvent` (orchestrator.js:210-216) republishes `production.item` with `{progress, source}` from the underlying job's progress event. So a Production Item has `source:'flow'` only while Flow shows a percent.

Docs on the shape of the Flow percent (docs/flow-ui-findings.md, "Progress and completion"): it is Flow's own, not linear (images climbed to 77 then flipped, videos 10 to 100 and 31 to done). A video tile shows `3%` right after submit. Timing seen live: images about 40 s; Omni 360p 4 s about 30 s; Veo Lite 8 s about 70 s; edit 85 s. "Failed or blocked tile: not observed." Extend: no percent.

`job.progress_source` is the app's field: `src/gen/models.py:51` (`"flow"` Flow's own percent; `"phase"` only the engine's stage). Values in use: `""`, `"flow"`, `"phase"`. (There is no engine "source" value other than `flow` and `phase`: grep of E/ shows only those two.)

### B2. Where the app sets `progress` / `progress_source`

| Path | File:line | What it does |
|---|---|---|
| App-started job, start | `run_engine_job` web_flow_image.py:101-102 | `ctx.note("phase")`, then `ctx.progress(0.05)`: a hard-coded 5 % before anything has happened. |
| App-started job, events | `report_event` web_flow_image.py:70-83 | On `job.progress` with a non-null `progress`: `note(event.source)`, `progress(value/100)`; `previewPath` -> `ctx.partial` (live preview). On `job.transition`: `ctx.note("phase")` (the value is left alone, so the last Flow % remains with `source=phase`). |
| App-started job, end | web_flow_image.py:119 | `ctx.progress(1.0)`. |
| Queue plumbing | queue.py:192-212 | `progress()` clamps 0..1 and triggers `on_update`; `note()` sets `job.progress_source` (:208-209); reset to 0.0 at the start of each attempt (:196) but `progress_source` is NOT reset there (only `Job.reset()` models.py:63-67 does). |
| Production rows | `item_fields` run_mirror.py:78-79 | `progress = 1.0` if status DONE else `event.progress/100` (null -> 0); `progress_source = event.source or ""`. |
| Agent (non-Production) rows | `row_state` engine_client.py:205-213 | `progress = 1.0 if done else 0.0`; `progress_source` is not set. `RunMirror._follow` explicitly ignores `job.progress` events (run_mirror.py:121). Result: an agent's single job never shows a percent. |

### B3. `run_mirror.py` behaviour (src/web/run_mirror.py)

- Manifests (`runs.jsonl` -> `manifest.json`) are the truth. SSE events only say "look again" (docstring :3-7). At start it catches up (`refresh` :208, `catch_up` :125), then `_follow` :113 reads `GET /events` forever.
- `production.*` events are applied directly (`apply_production_event` :155). `production.item` -> `_apply_item` :168; `production.summary` -> banner and `page.set_production_summary` (:160-166).
- Every other event type except `job.progress` triggers one debounced `refresh()` (`_queued` flag :121-123).
- `refresh()`/`_apply()` (:208-248) map manifest job `state` through `row_state` (engine_client.py:205-213): `done -> DONE`; `failed -> FAILED`; `cancelled`, `needs_user`, `paused -> STOPPED`; **everything else, including `queued`, `preparing`, `submitted`, `downloading`, `verifying`, maps to RUNNING** (`.get(state, JobStatus.RUNNING)` :211). A 20-job agent run therefore shows 20 amber frames from the moment it is enqueued, not just the one that is generating.
- `_same` (:251) compares only `(status, outputs, error)`, so engine stage changes that do not change those are not even refreshed.
- Jobs with key `app:` (the app's own) and `prod:` (Productions) are skipped by `refresh()` (`SKIPPED_KEYS` :26, :213). For Productions the app uses `flow_production_status detail=full` (:144), paged by `next_cursor`, then events.
- Missing from the mirror: the engine's own pause state (`worker.paused`, `queue_paused`), the active job id, the daily-cap state, `attempt`, `history` (prior paid attempts), `heldFrom`, and timestamps. `production.summary` already carries `paused{reason,code,quoted,item}` but the banner only prints the reason words (:51-53).

### B4. What the UI reads

| Reader | File:line | Field | Behaviour |
|---|---|---|---|
| Queue table "Progress" column | prompt_model.py:130-131 | `int(round(job.progress*100))` | Shows a bare number regardless of `progress_source`. Tooltip (:155-158): "Flow reports N%" for `flow`, "Waiting on a step; Flow has reported no percent yet" for `phase`. |
| Sheet frame bottom bar | sheet.py:247-249 inside `_paint_rebate` (:222) | `job.progress` | When `RUNNING` or `regenerating`: a 2 px amber bar of width `max(0.02, min(1.0, progress))`. Does not look at `progress_source`; so a `phase` job shows the 5 % invented in B2 (or 2 % minimum for production items with progress 0). |
| Sheet edge text | sheet.py:134-144 `edge_state` | `job.review`, `job.status` | Word only: REVIEW / APPROVED / REJECTED / RUNNING / QUEUED / etc. No elapsed, no %. |
| `RunStrip` | sheet.py:425-466 | `status`, `review` | A coloured tick per frame (amber live, etc.). No time. |
| `TakePanel` | take_panel.py:119-160 | `index`, `item_id`, `edge_state`, `error`, prompt, cast, scene, refs | No progress, no elapsed, no take history, no attempts. |
| `TakeViewer` | viewer.py (class at :68) | image/`status` | Does not show progress. |
| `StatsHeader` | stats_header.py:11-53 | counters and local clock | See B5. |
| Run banner `run_notice` | page.py:167, 349-357 | `production_banner` string | Counts and credits text from `banner_text` (run_mirror.py:39-56). |
| Sidebar amber mark | main_window.py:125-130 | `queue.is_running()` | Only the in-app `JobQueue`; an agent or Production running in the engine does not light the rail. |
| Webhook API | webhook/backend.py:35 | `round(job.progress, 3)` | Same invented number. |

### B5. Elapsed time: what exists and where it could come from

Today (the only timer): `StatsHeader` keeps a wall-clock of the app's own batch: `start_clock/stop_clock/reset_clock` stats_header.py:25-43, called from `GeneratorPage.start` (page.py:783-784), `_retry` (:808), `_on_finished` (:834), `clear` (:745). It formats `h:mm:ss` into the stats line (`gen_stats` en.py:122). It is page-wide, restarts at each Start, is the local app queue's lifetime, and knows nothing of the engine, per-row time, an agent run, or a Production. No `Job` field holds a start/finish time (models.py:34-69 has none); nothing persists.

Timestamps that already exist in the engine:
- Per job in `manifest.json` (written run-folder.js:63; the job object from job-store.js:62-66 + `apply` :45-58): `createdAt`, `updatedAt`, `submittedAt` (set when the job first reaches `submitted`, i.e. the Start click, job-store.js:46), `attempt`, `history[{attempt, submittedAt, error}]`. `submittedAt` is the best "generation clock started" stamp; it is cleared on a paid retry and the old one moved to `history`.
- Per event in each run's `events.jsonl` (`ts` on every record, E/engine/journal.js:23): the exact time of every state transition, including `generating` and `downloading`.
- Per SSE event: `hub.publish` adds `seq` and `ts` (server.js:29). `EngineClient.events` yields the whole dict, so `event["ts"]` is already in Python for `job.transition` and `job.progress` and is thrown away.
- Per Production take: no start/finish time in the take object (state.js:97-100; only the verdict `at`), but each take has `job_id`, which maps to the manifest job and so to `submittedAt`; `credits_spent` and `take_done` journal events carry `ts`.
- Not exposed anywhere: an ETA. `flow_production_plan` returns a crude `eta_minutes = images*1 + videos*2` (production/plan.js:15, 228); no live ETA, and Flow gives no ETA (its percent is non-linear).
- Engine/process time: `/health.uptimeMs` (server.js:109).

### B6. Where the UI invents or fakes a number

1. `ctx.progress(0.05)` at job start (web_flow_image.py:102): 5 % before anything is known. It is also the first thing the sheet bar draws.
2. `max(0.02, ...)` minimum bar width (sheet.py:248): a running frame always shows a visible bar even at 0 %.
3. Table "Progress" column prints the number for `phase` jobs as if it were a percent (prompt_model.py:130-131); only a tooltip admits it is not (:155-158).
4. `progress=1.0` for any DONE status including `pending_review` and for local jobs (queue.py:218, run_mirror.py:78); fine, but it makes "100 %" mean "has a file".
5. Stale source: `progress_source` stays `"flow"` after the last Flow percent, then flips to `"phase"` on `job.transition` (web_flow_image.py:82-83) while `progress` still holds the old Flow percent, so the bar can show e.g. 77 % with a tooltip saying "waiting on a step".
6. `row_state` maps queued/preparing/submitted/downloading/verifying to RUNNING, so unstarted agent jobs look live (engine_client.py:211).
7. Stats line: `Running N` counts rows with `RUNNING` status, which includes those queued agent jobs (B3).
8. The local `quote()` credit price (web_flow_video.py:13-25) is a table lookup, not Flow's live quote; the engine reads Flow's live quote at Start and may stop on `quote_drift`.
9. Elapsed clock is the app's own wall clock, not the engine's (B5).

### B7. State on the real Flow page that the engine does NOT mirror to the app

Establishing sources: docs/flow-ui-findings.md, E/flow/*.js, E/tools/flow-status.js. Items I could not confirm from code or docs are marked UNKNOWN.

- Other running tiles' percent: only the first running tile is reported (observe.js:97). With count 4 the other three are invisible.
- Whether a tile failed: observed text is kept only on the engine job error (`tile_text`), not on the app frame except as the error string; the failure mode itself "not observed" live (findings).
- Flow's balance and reset date: read only by `getBalance` (flow-status.js:16-28) at status/preflight, cached 60 s in `ledger.json` (`recordBalance`). The app never reads it, and the balance lags "by minutes" (findings, Video pipeline). The "Resets <date>" text next to it is not captured.
- Daily/monthly limits: `ledger.todayQuota` and `monthTotal` are the engine's own tally of its own spend, not Flow's. Anything the owner generates by hand in Flow is not counted.
- Anything the owner does by hand in the Flow tab: tiles favourited, renamed, shared, set as project cover, moved to trash, flagged (tile menu list in findings, Y0 corrections); project renamed in Flow (the app compares title only at `ensure_project`, flow_mcp.py:152-153); project deleted in Flow (app learns only on the next job: `PROJECT_NOT_FOUND`, flow_mcp.py:183-186); assets uploaded by hand; settings panel changed by hand (Kind, Model, Ratio, Count, etc.: the engine re-sets and verifies them on every job, settings.js:36-45).
- Project grid contents beyond the 28 newest tiles (`flow_list_assets` limitation, rpc.js:287 note; reconcile.js error text "grid shows only the newest 28 tiles").
- Flow-side Extend/Edit version history of a clip (edit "adds a new version to the clip's history", findings) and Scenes timelines.
- Tab state: closed Chrome/tab, navigation away, account switch. Detected only when a job runs (`session.ensure`, `STOPS_QUEUE` worker.js:18) or on `flow_status`/`flow_connect`; `/health` would show `worker.active/paused` but the app never polls it.
- Queue pause reason (WAF block, verification, daily cap, owner stop): in `/health.worker.paused` and `flow_wait.queue_paused`, but app rows only show it when that job's own `_follow` loop catches it (flow_mcp.py:219-229). For agent runs: not shown at all (non-Production); for Productions only as the generic banner `paused: <reason>`.
- Credits actually spent per job: written to `ledger.json` (`recordSpend`) and to Production takes (`quoted_credits`); neither is read by the app.
- Silent-video audio check result (`audio_streams`, `original` file): in the take, dropped by the app.
- Agent chat/Agent toggle: the engine forces direct mode (findings: "The big one"). UNKNOWN: whether the owner could usefully use Flow's agent alongside.
- Flow's own notifications/toasts ("Your video has been downloaded!") and promo popups: not mirrored; popups are auto-dismissed (flow/session.js:28).

---

## C. Feature parity with the Google Flow page

Source docs: docs/flow-ui-findings.md (Task 2 spike + Y0 + video + Production live notes), docs/flow-live-acceptance.md (Task 19), docs/production-live-acceptance.md (Y8), mcp/google-flow/README.md (stale; only used for the tool list). Drives = the engine has a tool or internal step. App = the Labs Studio UI exposes it. UNKNOWN = the docs do not establish it; I make no claim about the current real page.

| Flow page feature / button (doc source) | Engine drives it? | App exposes it? |
|---|---|---|
| Direct mode: composer with Agent toggle off, chat panel closed (findings "The big one") | yes, `session.js` closes chat, `project.agent`/`project.chatClose` keys | n/a (internal) |
| Settings trigger: Kind Image/Video | yes (settings.js:36) | yes (page = image/video) |
| Video mode radios Frames / Ingredients | yes (`settings.mode.*`, validate.js `videoMode`) | Ingredients only (refs); Frames: no (A12) |
| Ratio image 16:9 4:3 1:1 3:4 9:16; video 16:9 9:16 | yes | yes (config fields) |
| Model family menu (image: Nano Banana 2.1, Pro, 2 Lite; video: Omni, Veo Lite, Fast, Quality) | yes (`settings.model.*`) | yes |
| Omni resolution 360p/720p and duration 4/6/8/10 s | yes | yes, but duration list is shown for Veo too (A8) |
| Count x1-x4 | yes | yes (spinner to 8 then clamped to 4) |
| Live credit quote ("Generating will use N credits") | yes: `settings.credits` read, compared to `max_credits`, `BUDGET_EXCEEDED` / quote drift | indirectly (budget dialogs); live quote not shown |
| Start / Stop of the composer | Start yes; `project.stop` key exists in contract but I found no engine code that clicks it (grep for `project.stop` in `E/`: only the contract entry) | no. UNKNOWN whether cancel stops the generation inside Flow; docs only say a cancelled job after the credit line "let the download finish" (rpc.js:219-220 comment) |
| Prompt box typed | yes | yes |
| Add ingredients picker: tabs All / Images / Videos / Voices / Characters / Avatars / Uploads, project select, search, Upload media (file chooser), Add to prompt | All, Images, Uploads, Characters used (ingredients.js, doctor PICKER_KEYS); Videos, Voices, Avatars: contract entries only | files and characters/scenes yes; Voices/Avatars/Videos no. UNKNOWN: pull an existing Flow asset (by id) into a prompt from the app: not available |
| Start / End frame chips, Swap first and last frames | Start/End yes (`addFrame`); Swap: contract key only | no (A12) |
| Ingredient chips (count asserted; image limit at least 16; video limit unknown) | yes (`assertChips`) | via refs; limit not shown |
| Tile status: `n% <prompt>` | yes (observe.js) | yes, but see B (invented 5 %, first tile only) |
| Finished image/video tiles, media id identity, new-tile baseline, 28-tile fixed window | yes | n/a |
| Failed tile text | yes (`tile failed`, kept text); live occurrence not observed | error string only |
| Asset info popover (model, ratio, duration, resolution) | yes, used for verification (download.js:55) | no |
| Tile hover menu: Download (sizes 1K/2K images; 360p/720p video; upscales; GIF), Reuse prompt, Animate, Add to prompt, Copy, Rename, Share, Set project cover, Flag output, Move to trash, Favorite | Download with size yes; the others: NOT driven (listed in findings only) | Download is implicit in a job; the rest no. "Animate" (turn a still into a video) is not exposed but Productions do the equivalent with a start frame |
| 4K upscaled download (disabled on Pro per findings) | no | no (UNKNOWN on other plans) |
| Open clip editor `/edit/<id>`; Save frame; Move to trash; Download media | open yes; Save frame: contract-less; trash no | no |
| Add clip -> Extend (Veo 3.1 Lite only; disabled on Omni) | yes (clip.js `extend`), but the "completion marker and scene download still unobserved" at the time of the findings; later notes say the marker is the new timeline clip's thumbnail strip | no (A13) |
| Omni edit ("Describe how to edit this video...", 20 credits) | yes (clip.js `edit`) | no |
| Download scene (export joined clips) | yes (`editor.downloadScene`) | no |
| Return silent videos page setting | contract entry only; deliberately not trusted (findings: audio still present); engine strips audio locally with ffmpeg | yes: "silent" checkbox (web_flow_video.py:41) |
| Page settings: View mode, Grid size, Sound on hover, Show tile details, Clear prompt on submit | contract entries `pageSettings.*` only; no code calls them | no |
| Account details: balance, Resets <date> | balance read (flow-status.js:16); reset date not read | no (A4, A39) |
| Project home: list projects, create, open, rename title, delete | yes (open-project.js; list/rename/delete tools) | open/create/rename implicit; list/delete no (A45-A48) |
| Project sidebar: Images, Videos, Uploads (appear when assets exist), Characters, Scenes | Characters yes; Scenes: engine repurposes a character marked as a place, because Flow's own Scenes are video timelines (README, flow-ui-findings "Scenes") | Characters and Scenes pages (as place-characters) |
| Characters: Create character (upload / describe), name, Add from project, Done, picker Characters tab auto-attach | yes | yes (Set up in Flow) |
| Scenes: `New scene` creates an Untitled scene immediately (harmless-click trap) | avoided | n/a |
| Tools page: My creations, Create New; Grid Architect | not reachable; removed (findings C6) | n/a |
| Promo pop-up "Got it" | auto-dismiss (session.js:28) | n/a |
| WAF / "unusual activity" block, reCAPTCHA | detected (`detectBlock`, blocks.js) and stops the queue (`WAF_BLOCK`) | Rolled into a stop message + bring-to-front (map_engine_error web_flow_image.py:54) |
| Generation via `batchexecute`; stay on page only (no API) | by design | n/a |
| Agent mode with plan/permission radios ("Confirm Always") | not used | n/a (UNKNOWN value) |
| Quota stop from Google ("daily limit exhausted") | designed, not provable on demand (production-live-acceptance.md) | n/a |
| Quote drift (price changes between quote and Start) | designed, not provable live | banner text only; no accept button (A27) |
| Credits per model at Pro: Omni 7/10/12/15 at 720p, 360p 4/5/6/7, Veo Lite 10, Fast 20, Quality 100; images 0 credits but daily quota (Banana Pro 100/day, 2.1 and Lite 1000/day) | encoded in config/capabilities.json | credit table used by `quote()`; image daily quota not shown |
| Monthly credits 1000 + 50 daily bonus (capabilities `limits`) | `checkBudget` uses monthlyCredits (budget.js:42-50) | no |
| Character-mode reference (Flow Character as ingredient) vs ingredient mode | both (`referenceMode`) | no choice (Production start is agent-only) |

Anything about the current live page beyond the spike on 2026-11-02 (menus, new models, plan tiers other than Pro): UNKNOWN.

---

## D. Ten biggest gaps for a solo video producer who reviews batches

Ranked by value. Contact Sheet shell parts: rail (sidebar), run bar (title, Start/Pause/Stop, stats, RunStrip, banner), tool row (import/filter/size/inspector), sheet or queue, Inspector Take/Shot panels, or a new page.

1. **Real progress, queue state and elapsed per take (replace the invented numbers).**
   Control: on each frame, show the engine stage word (QUEUED / PREPARING / GENERATING / DOWNLOADING / VERIFYING) and, only when `source=flow`, a true percent; elapsed from `submittedAt` on the edge strip; show a hatched or indeterminate bar for `phase`. Drop the 5 % seed and the 2 % floor. Run bar: engine-wide "paused: <reason>" chip and a "Resume" action when `worker.paused` is set; stats line should say "Queued in engine" separately from "Generating".
   Data: already exposed (events carry `ts`; manifest has `submittedAt`; `/health.worker.paused`). Missing small read path: add `started_at`/`submitted_at` and `stage` to `itemView` (E/production/orchestrator.js:52-73) and map `row_state` stages instead of collapsing them to RUNNING.
   Files: `src/web/engine_client.py` (row_state 205), `src/web/run_mirror.py` (item_fields 59, `_follow` 113, `_same` 251), `src/gen/models.py` (add stage/started_at), `src/ui/generator/sheet.py` (_paint_rebate 222), `src/ui/generator/prompt_model.py` (130-158), `src/ui/generator/stats_header.py`, `src/ui/generator/page.py` (run bar), `src/gen/web_flow_image.py` (report_event 70, remove 0.05 at 102), `mcp/google-flow/src/production/orchestrator.js`.

2. **Credits and quota meter (balance, month, daily image quota, batch estimate).**
   Control: run bar or rail footer "Balance 812 · month 188/1000 · Banana 2.1 ≈ 940 images left"; Start shows "This batch ≈ 36 credits, cap 60" with a confirm and a run-level cap field; the video page blocks impossible model/duration pairs before Start.
   Data: yes (`flow_status.balance`, `.ledger.monthTotal`, `.ledger.todayQuota`; `flow_estimate`; capabilities `limits`). Poll `flow_status` only when idle (it refuses to touch the page while a job runs). Reset date: missing, needs one more text read in `getBalance` (flow-status.js:16).
   Files: `src/web/flow_mcp.py` (status 245), new `src/ui/kit` widget, `src/ui/generator/page.py` (run bar, `start` 771), `src/gen/web_flow_video.py` (duration list from caps, run-level `max_credits`), `src/ui/generator/config_panel.py` (count max 4).

3. **Take history and compare in the Inspector Take panel.**
   Control: a take strip (T1, T2, T3...) under the preview with prompt used, refs used, credits, verdict, who/when; compare two takes side by side; approve a specific older take; "keep both" default as the engine already allows. Show `stale` as a badge and filter.
   Data: yes. `flow_production_status detail=full` already returns `takes[]`; `item_fields` discards it (run_mirror.py:71-75).
   Files: `src/gen/models.py` (add `takes: list`), `src/web/run_mirror.py`, `src/ui/generator/take_panel.py`, `src/ui/generator/viewer.py` (step through takes), `src/ui/generator/sheet.py` (take badge), `src/web/production_actions.py`.

4. **Plan and start a Production from the app (and set review gates, cap, reference mode).**
   Control: new page or sheet empty-state: "Open a moodboard + prompts folder" -> plan summary (cast, shots, parse errors, estimate, eta) -> Start with `max_credits`, gates toggles, `reference_mode`, `cast_confirmed`.
   Data: yes (`flow_production_plan` returns errors and `analysis_needed`; `flow_production_start`). Nothing missing in the engine.
   Files: new `src/ui/production/` page, `src/web/production_actions.py` (add `plan`, `start`), `src/ui/sidebar.py` + `src/app.py` (register page), `src/ui/generator/page.py` (hand-off to the sheet).

5. **Run controls that match the engine: pause/resume/cancel a Production or run, accept quote drift, raise cap.**
   Control: run bar buttons act on the visible run when it is an engine run: Pause run, Resume, Cancel; banner action buttons "Accept $N quote" (quote_drift), "Raise cap to N" (budget), "Resume" (owner/stopped). The existing in-app Pause stays but is relabelled "Pause local queue".
   Data: yes (`flow_job_control` pause/resume/cancel/set_budget with run_id; `summary.paused{reason,quoted,item}`).
   Files: `src/web/production_actions.py`, `src/ui/generator/page.py` (`toggle_pause` 813, `stop` 820, `_update_controls` 845, `set_production_summary` 356), `src/web/run_mirror.py` (carry run_id, paused to the page), `src/languages/en.py`.

6. **Frames: use a finished still as a video's start/end frame, and "use last frame" for continuity.**
   Control: Take panel / context menu on a still: "Animate from this still" (sets `start_frame`); on a video: "Use last frame as next start" (`last_frame`); a Frames toggle in the video Settings with Start and End slots.
   Data: yes (`start_frame`, `end_frame`, `last_frame`). Small gap: the app's `WebFlowVideoProvider.generate` never passes them and `Job` has no field for them.
   Files: `src/gen/models.py` (start_frame/end_frame), `src/gen/web_flow_video.py` (args), `src/web/flow_mcp.py` (new `last_frame` call), `src/ui/generator/take_panel.py`, `src/ui/generator/page.py` (menu `_sheet_menu` 466), `src/ui/generator/prompt_table.py`.

7. **Stitch approved takes into a cut (and voice/music).**
   Control: run bar or tool row: "Assemble approved" -> order = sheet order, shows a result card and opens `final/<name>.mp4`; optional voice (Fish free model) and music lines via a small side panel.
   Data: yes (`stitch_video auto:true`, emits `job.progress stage:'stitch'` the app should show; `audio_voice_*`, `audio_stable_generate`, keys already pushed). The in-app editor stitcher exists (src/editor/stitch.py) but is not connected to the sheet; pick one. Prefer the engine one for approved Productions (it is already in the run folder).
   Files: `src/web/flow_mcp.py`, `src/ui/generator/page.py` (tool row), new small dialog, `src/web/run_mirror.py` (stitch progress, ignore `jobId`-less events today).

8. **Connection / account / Flow-project status chip with one-click Open in Flow and show-me.**
   Control: rail footer chip "Flow: connected as <acct> · project <title>" with menu: Open in Flow (bring to front), Take screenshot, Run Doctor (inline pass/fail), Switch/list Flow projects. A warning state when `/health` shows `worker.paused` (WAF_BLOCK, verification).
   Data: yes (`flow_connect`, `flow_status`, `flow_doctor`, `flow_screenshot`, `flow_list_projects`, `/health`). The check tools need the tab (JOB_IN_PROGRESS while a job runs), so poll only idle.
   Files: `src/ui/sidebar.py`, `src/ui/main_window.py`, `src/web/session.py` and `flow_mcp.py`, `src/ui/pages/web_sessions_tab.py` (reuse actions), `src/web/engine_client.py` (health helper).

9. **Agent and engine activity on the rail and the run list (what is running that I did not start).**
   Control: rail amber mark and a "Runs" drawer listing engine runs (name, kind, N/M done, credits, state) from `flow_list_runs`/manifests, with a per-row jump to the frames; queued agent jobs shown as QUEUED, not RUNNING.
   Data: yes (manifests, `flow_list_runs`, events). Fix `row_state`'s catch-all.
   Files: `src/web/engine_client.py`, `src/web/run_mirror.py`, `src/ui/main_window.py` (`_update_live` 125 uses only `queue.is_running()`), `src/ui/sidebar.py`.

10. **Shot-level settings and ingredient control in the Shot panel; remove silent clamps.**
    Control: a Shot (per-frame) settings block in the Inspector: model/ratio/count/duration/resolution per frame instead of page-wide; durations filtered by the chosen model's capabilities; refs with per-ref role (ingredient, start frame, end frame); count capped at 4; show `max_generation_retries` and engine attempt count ("attempt 2, 1 paid retry") so the producer knows what they are spending.
    Data: yes (`capabilities.json models.*.credits`, `jobView.attempt`, `history`).
    Files: `src/ui/generator/config_panel.py` (COMMON_FIELDS 20: count max 4), `src/gen/web_flow_video.py` (39: duration from caps), `src/gen/web_flow_image.py` (`max_generation_retries`), `src/gen/models.py`, `src/ui/generator/take_panel.py`.

Lower: Re-download a lost asset (`flow_download`); list/browse Flow project assets beyond app rows (`flow_list_assets`, 28-tile window); Veo extend / Omni edit; engine batch with `stop_on`; scenes list; page settings (Show tile details etc.).

---

## Surprises worth knowing

1. `mcp/google-flow/README.md` documents tools that do not exist (`flow_account_check`, `flow_queue_status`, `flow_use_grid_architect`, ...) and Imagen 4.
2. The sheet's amber bar and the table's Progress column draw a number the app invented (0.05 at start, 2 % floor) and do not check `progress_source`; `row_state` marks every non-terminal engine state RUNNING, so a queued agent job looks live.
3. The app's Pause/Resume buttons never touch the engine; the app has no resume for any engine queue pause except the daily-cap case.
4. The app already downloads each Production Item's full `takes[]` and `quoted_credits`, then keeps only one file path.
5. `FlowMcp.status` / `flow_status` has no UI caller, so no balance, month total or image quota appears anywhere.
6. `ledger.json` is not read by the app; `pacer.json` is (for "used today").
7. The count spinner allows 8 and the duration list shows 4/6/8/10 for Veo; both are silently clamped or rejected later.
