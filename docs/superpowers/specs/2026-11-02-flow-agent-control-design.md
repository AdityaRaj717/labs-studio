# Labs Studio: agent-controlled Google Flow MCP (design)

Date: 2026-11-02. Owner's account: Google AI Pro, 1,000 Flow credits a month. Personal use.

## 1. Intent

Give any AI agent a plain instruction ("make this 12-shot story with voiceover and music") and have it finish the job through one MCP, from a single image up to a batch of hundreds. Labs Studio becomes the local window onto that work. Whatever an agent is doing shows up in the app, truthfully and live, and every result is saved.

Priority: finish the main workflow first. **UI layout is frozen** until the owner describes the overhaul.

## 2. Decisions from the owner

- Main purpose: Google Flow image and video. Remove features unrelated to that pipeline.
- A run always saves raw assets in organised project folders: Flow images and videos, Fish Audio voiceover, Stable Audio BGM and SFX.
- A lightweight FFmpeg stitcher stays. The agent can optionally assemble one finished video. FFmpeg is not removed.
- Fish Audio on its free API route. Stable Audio 3 for music and SFX.
- Rigid failure handling. Accurate progress sync. Quality-of-life features. No UI changes for now.
- The owner accepts the terms risk for their own account.

## 3. Calls made by the planner (check these)

| # | Call | Why |
|---|---|---|
| C1 | One background **engine** owns the browser; MCP and app are both its clients | See section 6. Two owners of one tab is the root cause of several bugs |
| C2 | Keep evolving the vendored Node server rather than adopt `gflow-cli` | See section 5 |
| C3 | Drive the page only; never call Flow's internal `batchexecute` | Prior art shows reCAPTCHA blocks, and the protocol is shifting |
| C4 | Stable Audio ships through the official API first; local Small models are an optional later task | Local needs torch, CUDA, a gated download and a separate venv. API is 8 credits ($0.08) a track after 25 free credits, so about 3 free tracks. If "free only" matters, swap the order |
| C5 | Delete the GUI video editor and Video Cut pages, keep `src/editor` engine code | "Lightweight stitcher". Both pages are already hidden by default, so nothing visible changes |
| C6 | Tools Gallery and `flow_use_tool` are removed. Grid Architect is removed unless the Task 2 probe finds it reachable in the current UI | Live `/tools` showed only "My creations" and "Create New" for this project; these tools are built on dead French selectors |
| C7 | Webhook page stays, retargeted to Flow pages | It's visible in the sidebar today; removing it changes the UI |
| C8 | Audio results are saved and reachable through agents and folders, with no new app page yet | A new page is a UI change; add it during the overhaul |
| C9 | CAPTCHA, "verify it's you", and limits always stop and hand over to the owner. No stealth, no solver, no retries past them | Retrying raises the account's risk. Project rule, and the terms page promises it |

| C10 | **Drive Flow's direct composer (Agent toggle off), not its agent chat** | Found in the Task 2 spike. Real controls for every option, a live credit quote, and no agent to rephrase or ask questions. See `docs/flow-ui-findings.md`, which overrides any conflicting detail in sections 4.2-4.3 |
| C11 | `silent: true` strips audio locally with FFmpeg and keeps the original | Spike: Flow's Return silent videos setting still returned audible audio |
| C12 | Before Start, the engine reads Flow's quoted credits; above `max_credits` it stops with no spend, and the ledger records the quote | Replaces estimates with Flow's own number. The account panel gives the real balance |

## 4. What the investigation found

### 4.1 Code

- `flow_generate_video` never clicks Generate or downloads. The app has no Flow video provider. **Flow video is new work.**
- `job.updateProgress` is never called; the app's bar jumps from 5% to 100%. The stdio client also discards notifications.
- A second job gets `JOB_IN_PROGRESS`, so there's no real batching. History is memory-only, so a restart loses a `running` job's result. Default history is 5 entries.
- Pacing and the daily cap exist only in the app's provider, so direct agents skip them.
- Read and navigate tools (`flow_discover_ui`, `flow_download_latest`) use the tab unguarded, and can hijack a running generation. The app's `BrowserSession` also opens its own Flow tab, which the MCP can adopt.
- The refusal path only ends on the "Good response" control, so an error bubble waits out the 300s timeout.
- `flow_account_check` passes with no expected account set.
- There are no MCP tests, no CI, and `npm test` points to a missing script.
- Leftovers: French selectors, `labs.google` host checks, `launchKiaraProfile`, "Profile 3".
- `selectors.map.json` is unused and overwritten on each discovery run.

The nine logged issues are all real but are a subset. The log's "100% passed" sections ran with `auto_confirm: false`, so they don't prove generation works.

### 4.2 Live Flow, read-only, 2026-11-02 (no credits spent)

- Flow is on `flow.google.com` in English, showing the PRO badge on the owner's account. Generation goes through a per-project **agent chat**.
- Agent settings: Confirm (Always, Never); image ratio 16:9, 4:3, 1:1, 3:4, 9:16; image count x1-x4; image model Nano Banana Pro, 2 Lite, 2.1. Video ratio 16:9, 9:16 only; video count x1-x4; video model **Omni 1.1 Flash**, Veo 3.1 Lite, Fast, Quality. Config's "Omni Flash" is out of date. Radio groups have no names, so finding them by index is brittle.
- No duration control appears in Agent settings. Duration (4, 6, 8, 10s) and resolution (720p, 360p) appear in the filter dialog. How to set them for a generation is unknown (spike).
- **Escape does not close** the settings panel or an open menu. Code must close by control or backdrop.
- Picker tabs: All, Images, Videos, Voices, Characters, Avatars, Uploads.
- Download menu: 1K, 2K, and 4K (disabled on Pro).
- Page settings: Return silent videos, Clear prompt on submit, Batch view, Show tile details.
- Add media: Upload, New collection, Create character, New scene.
- The live progress display and video download menu haven't been seen. **Task 2 observes them.**

### 4.3 Flow rules (official help, 2026-11-02)

- Images use **no credits**, but have daily limits on Pro: Nano Banana Pro 100; Nano Banana 2.1 + 2 Lite share 1,000; 2K upscale 200. Failed or blocked images don't count. Very rapid generation may be rate limited.
- Video credits per generation, Pro: Veo Lite 10, Fast 20, Quality 100. Omni 720p 7, 10, 12, 15 for 4, 6, 8, 10s; Omni 360p 4, 5, 6, 7; Omni edit 40. 1080p upscale 0. 4K Ultra only.
- 1,000 credits a month with no rollover, plus 50 a day.
- Credits are deducted at start and returned within one hour on failure or safety block, and the shown balance can lag.
- Model capability: Veo T2V and frames at 4, 6, 8s (**live on Pro: 8s 720p only, no control**); Ingredients 8s, Lite and Fast only; Extend 8s, help says use Lite; Omni 4-10s with frames, ingredients, and edit.
- The Flow agent's own queries are free but have a daily query limit.

### 4.4 Lessons from `gflow-cli` (MIT, active, adopted as reference only)

Headed real Chrome is required. Selector drift is the main recurring failure. Flow is migrating hosts, with variation by page load. Uploads sometimes never get answered. Refuse rather than retry at a WAF or reCAPTCHA block. Use a persisted queue, and a canary that detects drift early.

### 4.5 Audio

**Fish Audio.** `POST https://api.fish.audio/v1/tts`, Bearer key, `model` header, JSON body with `text`, `reference_id`, `format`, `prosody`, `sample_rate`, `mp3_bitrate`, `latency`, `temperature`, `top_p`. Returns audio bytes directly.
- **Always send `model: s2.1-pro-free`.** A missing or unrecognised model silently falls back to the paid model.
- Free model limits are "fair use" with no numbers, and commercial terms are unverified. Fine for personal use; check before any sale.
- Errors: 402 no credit; 429 concurrency, no `Retry-After`; 503 load. Voices via `GET /model`. Emotion tags like `[whisper]` work on S2.
- Starter concurrency is 5; the engine uses 1.

**Stable Audio 3.** Music and SFX, not speech. `POST https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio`, multipart, `model: stable-audio-3`, `prompt`, `duration` 1-380s, `seed`, `steps` 4-8, `cfg_scale` 1-25, `output_format`. Returns 202 with `id`; poll `GET /v2beta/audio/results/{id}`; results last 24 hours. 402 credits, 403 moderated, 422 classification failed, 429 limits.
- Local option on the owner's RTX 3060 6 GB: Small music and SFX fit (about 2.4 GB). Medium is borderline and needs Flash-Attention 2. Weights are gated on Hugging Face.

### 4.6 MCP

- Current spec is 2026-07-28: stateless, and tasks moved to an extension. Claude Code supports progress, but its desktop app and VS Code extension have **no MCP tasks**. Stdio calls abort after 30 idle minutes, and output is capped at 25k tokens.
- So the design **depends on neither tasks nor progress**: tools start fast and return an id; `flow_wait` blocks at most 55s; progress notifications are a bonus.
- Stay on `@modelcontextprotocol/sdk` 1.x latest for the widest client support. Cursor and Codex support is unverified, so polling is the contract.
- Anthropic's tool guidance: fewer, consolidated tools, concise responses by default, errors that say what to do next, and real multi-step evals.

## 5. Approaches

| Approach | Upside | Downside | Verdict |
|---|---|---|---|
| **A. Evolve the vendored server into engine + thin MCP** | Reuses working image and character code; full control of progress and app sync; no new runtime | The most work on our side | **Chosen** |
| B. Adopt `gflow-cli` underneath | Active drift fixes, persistent queue | Its own issues report only t2i and t2v on the agent-only composer; alpha; Python worker and own state; app sync is bolted on | Reference only |
| C. Call Flow's internal APIs | Fast, exact progress | reCAPTCHA gates; changing protocol; highest account risk | Rejected |

## 6. Architecture

```
Any MCP agent --stdio--> MCP shim --+
                                    +--HTTP + SSE (127.0.0.1, token)--> Flow engine --CDP--> Chrome (Flow)
Labs Studio ---------EngineClient --+                                     |  |
                                                                          |  +--> Fish / Stability APIs
                                                                          |  +--> python -m src.stitch_cli
                                                                          +--> run folders, manifests, event log
```

- **Engine:** one Node process per machine. Whichever client comes first starts it, using a lock file `<dataDir>/engine.json` (`pid`, `port`, `token`, `version`). It owns the browser, one dedicated tab, the job queue, pacing, budgets and files. It binds to 127.0.0.1 only and requires a random token.
- **Shim:** `mcp/google-flow/src/index.js` stays the entry point in every agent's MCP config. It defines tools, forwards calls, and turns engine events into MCP progress. No browser code.
- **App:** `EngineClient` (Python) replaces the stdio `FlowMcp` transport. Its SSE thread feeds the existing `JobQueue` callbacks, so existing table cells update with no layout change. Jobs started by an external agent appear as rows on the matching page. If the app is closed, runs continue, and the app catches up from manifests when opened.
- **Durable state:** plain files, no database. Append-only `events.jsonl` and atomically written `manifest.json` per run. One user and one writer don't need more.

### 6.1 Job states

`queued → preparing → submitted → generating → downloading → verifying → done`, plus `needs_user`, `failed`, `cancelled`, `paused`.

**`submitted` is the credit line.** The journal writes it before clicking Start. After a crash, a job at or past `submitted` is never resubmitted automatically: the engine looks in the project for the result and downloads it if found, or else marks it `failed` with `credits_at_risk`. Only `flow_job_control retry_failed` or an explicit retry spends again. Download or disk failures retry the download only, never the generation.

### 6.2 Progress truth

`progress` carries a `source`: `flow` (a number read from Flow's own display) or `phase` (engine stage only). A percentage is never invented. If Task 2 finds Flow shows none, the bar shows stage-based values, and the agent sees `source: "phase"`. The newest thumbnail comes from the tile or gallery as soon as it exists.

### 6.3 Run folder

```
<project output dir>/runs/<YYYYMMDD-HHMMSS>-<slug>/
  manifest.json   events.jsonl
  images/  videos/  voice/  bgm/  sfx/  final/  diagnostics/
```

File names: `<seq>_<slug>_v<n>.<ext>`, never overwriting. Each manifest entry has prompt, sent request, requested and observed model, ratio, duration, count, Flow project URL, media URL or id if visible, sha256, dimensions, credit estimate, and timings. Project output dir: the app project's folder when linked, else `output_root` in the call, else `%APPDATA%\LabsStudio\outputs`.

### 6.4 Tool surface

| Group | Tools |
|---|---|
| Session | `flow_connect`, `flow_disconnect` (detach, Chrome stays), `flow_status` (browser, account, Flow page, active run, today's quotas), `flow_doctor` (read-only UI contract check), `flow_capabilities` (models, ratios, durations, compatibility, costs, limits, verified date) |
| Generate | `flow_estimate`, `flow_generate_image`, `flow_generate_video`, `flow_batch_start` |
| Watch and control | `flow_job_status`, `flow_wait`, `flow_job_control` (pause, resume, cancel, retry_failed), `flow_list_runs` |
| Assets | `flow_list_assets`, `flow_download` |
| Projects | `flow_open_project`, `flow_list_projects`, `flow_rename_project`, `flow_delete_project` |
| Library | `flow_create_character`, `flow_list_characters`, `flow_import_character`, `flow_create_scene`, `flow_list_scenes` |
| Audio | `audio_voice_generate`, `audio_voice_list`, `audio_stable_generate` (kind music or sfx) |
| Finish | `stitch_video` |
| Diagnose | `flow_screenshot` |

Removed: `flow_account_check` (in status), `flow_discover_ui` (replaced by doctor), `flow_queue_status` (replaced by job status), `flow_download_latest` (`flow_download` with `latest: true`), `flow_open_tools_gallery`, `flow_use_tool`, conditionally `flow_use_grid_architect`.

Rules:
- Spending needs `auto_confirm: true` and stays within `max_credits` (per call or run; default 30). A dry run never touches the browser.
- Invalid input fails before any browser work.
- Annotations on every tool. Concise output by default; `detail: "full"` on request. Each response stays well below 10k tokens.
- The server `instructions` field and a `flow://guide` resource teach a cold agent the workflow.

### 6.5 Error contract

Every failure returns `isError: true` with `{ ok:false, error_code, message, retryable, credits_at_risk, next_action, details, screenshot }`. `next_action` is one concrete step. Existing `error_code` stays, so Python mapping keeps working.

| Class | Codes | Engine behaviour |
|---|---|---|
| Stop for owner (`needs_user`, pause run, bring Chrome forward) | `NOT_LOGGED_IN`, `WRONG_GOOGLE_ACCOUNT`, `MANUAL_VERIFICATION_REQUIRED`, `WAF_BLOCK` | No retry. Resumes after the owner fixes it and calls resume |
| Stop run | `GOOGLE_LIMIT_REACHED`, `DAILY_MODEL_LIMIT`, `DAILY_CAP_REACHED`, `BUDGET_EXCEEDED`, `UNKNOWN_UI_CHANGE`, `AUDIO_NO_CREDIT` | Remaining jobs stay queued and resumable |
| This job only | `GENERATION_REFUSED`, `SAFETY_BLOCKED`, `AGENT_NEEDS_CLARIFICATION`, `RESULT_MISMATCH` | Mark failed, go on. Refund note for video |
| Retry safely, bounded | `UPLOAD_STALLED`, `DOWNLOAD_FAILED`, `NAVIGATION_TIMEOUT`, `BROWSER_NOT_CONNECTED`, `AUDIO_RATE_LIMITED`, `AUDIO_UNAVAILABLE` | Max 3, exponential backoff with jitter, only for steps before `submitted` or that repeat no spend |
| Retry with spend | `FLOW_GENERATION_FAILED` (error bubble, tile failed) | Default 0 for video, 1 for images. Raised by `max_generation_retries` |
| Caller fix | `INVALID_PARAMS`, `MODEL_NOT_AVAILABLE`, `RATIO_NOT_AVAILABLE`, `COMBINATION_NOT_SUPPORTED`, `PROJECT_NOT_FOUND`, `MISSING_API_KEY`, `FFMPEG_NOT_FOUND`, `JOB_NOT_FOUND` | Immediate, with valid values listed |

Since generation goes through Flow's agent, the engine **verifies the result**: count, ratio from pixel dimensions, duration from ffprobe, and model from asset info if shown. A mismatch keeps the files and raises `RESULT_MISMATCH`.

### 6.6 Pacing

One generation at a time, a random gap (config default 8-20s, ±25% jitter on interactions), and a daily cap (existing setting), all now enforced in the engine for every client. Parallel generation is out of scope unless the owner asks after live data. Pacing lowers load, but doesn't make the use allowed.

### 6.7 App changes without layout changes

- Removed pages per the audit. The sidebar stays visually the same for the default view, with `flow_video` becoming visible using the existing `GeneratorPage`.
- `Job.preview`, shown by the existing output-cell thumbnail until `job.outputs` exists.
- `ctx.progress` gets real values, drawn by the existing `ProgressDelegate`.
- The hidden API keys tab returns with Fish Audio and Stability rows, reusing its widgets. Keys stay in Windows Credential Manager. The app pushes keys to the engine's memory over its authenticated local link. An agent-started engine reads `FISH_API_KEY` and `STABILITY_API_KEY` from the environment.

### 6.8 Quality of life

Cost and quota preview before spending. Resume after crash or reboot. Retry only failed items. Idempotency keys so a repeated call doesn't spend twice. Per-run report with spend estimate. Credit ledger per month. Drift doctor with clear output. Failure screenshots in `diagnostics/`. JSON or CSV batch input. Skip already-finished rows. Last-frame extraction for shot chaining. Prompt and settings stored per asset, so any shot can be reproduced.

## 7. Scope

**In:** every Flow control that serves image and video: project lifecycle; agent settings; session reset; ingredients (upload, reuse, character, scene, across projects); text-to-video, first and last frames, ingredients to video, extend, Omni edit; Return silent videos; download sizes; upscale; asset info; trash for run cleanup; refusal, failure and quota states.

**Later or out:** Flow Music, Flow TV, tool creator, share, flag output, collections, Avatars, Flow's own Voices, Scenebuilder, multi-account, parallel generation.

**Anti-goals:** a passing test that never generated; silent spending; a made-up progress bar; lost output; any bypass of a Google check; UI redesign.

## 8. Testing

| Tier | What | Cost |
|---|---|---|
| T0 Unit | Node `node:test`, Python pytest, offline | None |
| T1 Fake Flow | Local HTML pages built from recorded accessibility snapshots, driven by real Playwright | None |
| T2 Doctor | Live, read-only UI contract | None |
| T3 Live images | Real image generation, daily limits only | Quota |
| T4 Live video | Fixed budget, mostly Omni 360p 4s | **Capped, owner approved** |
| T5 Cold-agent evals | A fresh agent gets only the instruction and the MCP, from easy to complex; score success, calls, wrong calls | Quota and credits within T4 cap |

Live budget: spike at most 40 credits; acceptance at most 300 of the 1,000, leaving the rest for real work. One Veo Quality test (100) is included only if the owner asks for it at the time.

## 9. Risks

- **Account:** a suspended account would also affect other Google services. Keep the dedicated profile and pacing. The owner accepted the risk.
- **Drift:** Flow is mid-migration, so breakage will recur. Mitigation: one contract file, doctor, fake-Flow fixtures refreshed from live snapshots.
- **Agent-in-the-middle:** removed by C10. If Flow drops the direct composer, `flow_doctor` reports it through the contract.
- **Failed tile UI unseen:** a blocked generation's tile wasn't observed in the spike. A tile leaving the running state without finished media is treated as failed and its text kept; refine when seen live.
- **Licence:** the vendored `LICENSE` calls the code MIT, but upstream's GitHub lists no licence. Fine for private use; settle before public distribution.
- **Fish free tier:** limits undocumented. Stops with a clear error and never moves to the paid model on its own.

## 10. Sources (retrieved 2026-11-02)

- Flow: [credits](https://support.google.com/flow/answer/16526234), [image limits](https://support.google.com/flow/answer/16729550), [get started and refunds](https://support.google.com/flow/answer/16353333), [models](https://support.google.com/flow/answer/16352836), [agent](https://support.google.com/flow/answer/17093911), [project settings](https://support.google.com/flow/answer/16935308)
- Fish Audio: [TTS](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech.md), [pricing](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits.md), [errors](https://docs.fish.audio/api-reference/errors.md)
- Stability: [text-to-audio](https://docs.stability.ai/api-reference/stable-audio/text-to-audio.md), [pricing](https://docs.stability.ai/pricing.md), [Stable Audio 3 repo](https://github.com/Stability-AI/stable-audio-3)
- MCP: [versioning](https://modelcontextprotocol.io/specification/versioning.md), [progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress.md), [tasks](https://modelcontextprotocol.io/extensions/tasks/overview.md), [Claude Code MCP](https://code.claude.com/docs/en/mcp.md), [writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- Prior art: [gflow-cli](https://github.com/ffroliva/gflow-cli), [host migration issue](https://github.com/ffroliva/gflow-cli/issues/639)

**Unverified:** Flow's failed-tile display, Extend and Omni edit runs (Tasks 10, 19); Fish free-tier numbers and commercial terms; Stable Audio licence wording; Cursor and Codex progress support; FFmpeg recipes until Task 18 tests them.
