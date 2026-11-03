# YouTube production on the Flow MCP (design)

Date: 2026-11-02. Builds on `docs/superpowers/specs/2026-11-02-flow-agent-control-design.md` ("base spec") and `docs/flow-ui-findings.md`. Where this conflicts with the base plan's task text, the rulings here win. Spike rulings stay in force unless a ruling below names them.

The owner was away, so the planner made these calls. Section 13 lists what only the owner can decide.

## 1. Intent

An agent gets a folder holding a moodboard file and a prompts file, then carries the job through with little help: character reference sheets first, then every still, then every silent animation. Each result waits for its own approval in the app. Retrying or changing one never touches another.

**In:** parsing, cast, reference sheets, stills, silent animations, per-item review and regeneration, autonomous ordering and recovery, live progress, Fish Audio and Stable Audio 3 API access.

**Later (Phase L):** voice selection and testing, audio editing, SFX placement, stitching, video editing, final assembly.

**Anti-goals:** spending on an animation from a still nobody cleared, an audio stream in a deliverable, a regeneration that changes another item, a percentage Flow didn't report, the engine pretending to understand prose.

## 2. Vocabulary

"Project" is already overloaded, so it is always qualified. `GLOSSARY.md` takes these terms in Task 20.

| Term | Meaning |
|---|---|
| **Production** | One video's whole job, from prompt files to approved assets. Owns one Run, and one Flow project unless told otherwise |
| **App project / Flow project** | The existing `src/projects` entry; the page at `flow.google.com/project/<id>`. The base plan's RunMirror links them through the Flow URL |
| **Moodboard file / Prompts file** | The two inputs. The prompts file holds stills, or stills and animations. It is a *Stills-only* file if it has no animations |
| **Reference** | A moodboard entry with kind `character` or `place`. A *Character Reference* is the kind `character`, and its image is a *Reference Sheet* |
| **Cast** | All References of a Production |
| **Shot** | One entry of the prompts file: a *Still* or an *Animation* |
| **Item** | Anything reviewable: a Reference, Still or Animation. One table row |
| **Take** | One generated result of an Item, numbered `v1, v2…`. Never overwritten |
| **Review state** | `pending_review`, `approved`, `rejected`, `regenerating` |
| **Approved Take** | The one Take of an Item that counts downstream. Other Takes stay on disk |
| **Stale** | An approved Item built from a Take that is no longer its dependency's Approved Take. Information only: never changes the Item |

## 3. Who analyses what

The MCP has no LLM. **The engine is deterministic; the calling agent supplies all judgement.**

| Job | Who | How |
|---|---|---|
| Table or block parsing, IDs, explicit references, name matching, estimates | Engine | `flow_production_plan`, no browser |
| Is this row one person or two? Which person is "the man"? Free-form files | Calling agent | Reads the files itself and answers through `overrides` or a whole `plan` JSON. The engine validates it exactly like parsed input |
| Approving results | Owner in the app, or an agent told to by the owner | `actor` is recorded on every verdict. The guide tells agents not to self-approve |

The engine reports what it couldn't settle in `analysis_needed`. `flow_production_start` refuses with `ANALYSIS_REQUIRED` while any remain, and needs `cast_confirmed: true`, which the guide defines as "I read both files and every Reference is exactly one subject".

## 4. Parsing

**Discovery:** `folder` matches, case-insensitive: moodboard `*moodboard*.md`; prompts `*animation*.md`, then `*still*.md`, then `*image*.md`, excluding the moodboard. Two matches at the same level is `PROMPT_FILE_INVALID` listing both; explicit `moodboard_path` and `prompts_path` skip discovery. Filenames only find files: **the mode comes from content**. `script.md` is ignored. `samples/zombie-bunker/` must parse unchanged. Its `MD_04` row has no kind tag, so it correctly lands in `analysis_needed`, and the caller passes `MD_04 → place`.

**Accepted shapes.** Headers are case-insensitive:

1. *Pipe table.* Moodboard: `ID`, `Prompt`, optional `Kind`, `Name`, `What it fixes`. Prompts: `ID`, `Prompt`, optional `Type`, `Refs`, `Start`, `End`, `Duration`, `Model`, `Resolution`, `Line`. `\|` is a literal pipe.
2. *Scene table.* `Scene|ID`, `Image prompt`, `Animation prompt`, optional `Refs`, `Duration`. Each row gives `<ID>_IMG` and `<ID>_ANI`, paired by an explicit start frame.
3. *Blocks.* A heading `### <ID>[: name]`, then `Field: value` lines. Text with no field is the prompt. A `## Characters` or `## Places` section sets `kind`; `## Still images` or `## Animations` sets `Type`. A block with no ID under `## Characters` gets `CH_<slug>` and its heading as the name.

**Deterministic rules:**

- **Global text:** in the lines before the first table or block, `Style…:` sets `style`, and exactly one ratio token sets the default ratio. Two different tokens is an error. None defaults to 16:9, with a warning. `style` is appended to every final prompt as `. Style: <style>`, and shown verbatim in `detail: full`.
- **Reference kind:** `Kind` wins, then section, then `(character)`, `(location)`, `(place)` in `What it fixes` (the sample's form), else `analysis_needed`. `Name` comes from `Name`, else the text before the bracket.
- **Shot kind:** `Type` wins, then section, then ID prefix: `IMG_ STILL_ SHOT_` still; `ANI_ ANIM_ VID_` animation. A conflict is an error.
- **Shot refs:** `Refs` lists IDs or exact names; `none` means none. With no `Refs`, whole-word exact name match in the prompt, marked `source: name`. No match and a Cast of people is `analysis_needed`. Prose like "the man from the reference" is never interpreted.
- **Start frame:** `Start` names a Still, or `none`. Absent, `ANI_nn` pairs with `IMG_nn` when that exists, and is listed in `implied` so the agent can overrule it. Otherwise there's no start frame.
- **Mode:** no Animations is `stills_only`. That starts no animation workflow: no video job, no `max_credits`, no FFmpeg check.
- **Animation settings:** `Duration`, `Model`, `Resolution` columns only, never from prose, else plan `defaults` (Omni 1.1 Flash, 720p, 6s). Task 6's validators apply before any spend.

**Strict errors, each with `file`, `line`, `code`, `message`:** not UTF-8 (BOM allowed), column count mismatch, duplicate ID across both files, empty prompt, unknown ref, `Start` or `End` not naming a Still, no Shots, no table or block found, more refs than a mode allows (limit from Y0; `null` means unchecked until the live composer refuses), an invalid model mix or a video ratio other than 16:9 or 9:16. Any error means `ok: false` and no plan can start. **Warnings:** a Reference no Shot uses, a Shot with no refs, a default ratio, a `plan` prompt not found in the source files.

**Dry-run report:** `flow_production_plan` returns `{ok, plan_id, mode, counts, cast, errors, warnings, analysis_needed, implied, estimate}`. `estimate` has credits by model, image quota by model, 2K count and ETA. It never touches the browser. `plan_id` hashes the inputs, overrides and defaults. If a file changes before start, it is `PLAN_CHANGED`.

**Reference Sheet prompt** (engine template, overridable as `sheet_prompt`), for kind `character`:

> Character reference sheet of {prompt}. One image showing the same person as full-body front, side and back views plus a head close-up. Show the full outfit, proportions and every defining detail. Neutral pose, plain light background, even light, no text, no labels.

Kind `place` uses the moodboard prompt unchanged. Defaults: Nano Banana 2.1, x1, 16:9, 2K download, as for Stills (1K is below 1080p). 2K counts against 200 a day.

## 5. Data model

No new store: a Production is a Run (base spec 6.3) plus one file.

```
runs/<stamp>-<slug>/
  manifest.json  events.jsonl          as Task 5
  production.json                      atomic; the review truth
  inputs/                              frozen copies of the two files
  references/  images/  videos/        deliverables
  videos/_original/                    Flow's file with audio, never shown
  diagnostics/
```

```
production: { id, plan_id, run_id, name, mode, style, ratio, flow_project_url, reference_mode,
              gates:{references, stills}, budget:{max_credits, spent}, paused:null|{reason,code},
              cancelled, last_seq, items:[item] }
item:       { id, seq, stage:'reference'|'still'|'animation', kind, name, prompt, refs:[id],
              start, end, settings, estimate, state, approved_take:null|n, takes:[take], last_error }
take:       { n, of_take:null|n, key, job_id, prompt, refs_used:[{item,take,file}],
              start_used:null|{item,take,file}, end_used:null|{item,take,file},
              status:'generating'|'done'|'failed'|'aborted', file, original, sha256, audio_streams,
              quoted_credits, credits_at_risk, verdict:null|'approved'|'rejected', actor, at, note }
```

`of_take` is the Take a regeneration replaces. `PlanDoc`, cached at `<dataDir>/plans/<plan_id>.json`, is `{plan_id, name, mode, style, ratio, sources:[{path, sha256}], defaults, references:[…], shots:[…]}`, with `analysis_needed` and `estimate` beside them, fully resolved after overrides.

**States:** `planned → generating → pending_review → approved | rejected`, plus `failed` and `regenerating`.

| From | Event | To |
|---|---|---|
| `planned` | scheduler starts Take | `generating` |
| `generating`, `regenerating` | Take done and verified | `pending_review` |
| `generating` | Take failed | `failed` |
| `regenerating` | Take failed | `approved` if it has an Approved Take, else `failed`; error kept |
| `generating`, `regenerating` | Run stopped before `submitted` | The state before the Take; Take `aborted`, next attempt is `n+1`, no spend |
| `pending_review`, `approved`, `rejected`, `failed` | approve a finished Take | `approved` |
| `pending_review`, `approved` | reject a Take | `rejected`, or back to `approved` if rejecting a newer Take while an older one stays approved |
| `pending_review`, `approved`, `rejected`, `failed` | regenerate | `regenerating` |

Regenerating an approved Item keeps its Approved Take in force until a new one is approved. A verdict always names its Take and acts on exactly that Take, never "the latest", so a batch approve can't approve a result nobody saw, and an older Take can be brought back the same way. Prompt changes live on the Item and Take; source files are never rewritten.

**Durability:** every change appends an `events.jsonl` event, then rewrites `production.json` with `last_seq`. On load, events past `last_seq` are replayed through the same reducer, so a verdict is on disk before the call returns. Approval needs no Chrome.

**Regeneration isolation:** the reducer only touches the named Item, and files are never rewritten. Once a new Take is approved, a dependent built from the old one becomes Stale and stays as it is. The agent or owner chooses whether to regenerate it.

## 6. Order

`nextItem(production)` is pure, and returns one Item. One job is in the queue at a time, so a Still freed by a late approval still goes before an Animation.

1. **References**, in file order, no dependencies.
2. **Stills**, once each Reference they use is approved (`gates.references`, default true). With the gate off they use the latest finished non-rejected Take, and are Stale if another is approved later. In `character` mode, the Flow Character is created here, as a scheduler step before the first dependent (also for reused References), because approval itself needs no Chrome.
3. **Animations**, after every runnable Still. With a start frame, it needs that Still approved (`gates.stills`, default true). Without one, it needs its References approved.

A failed or rejected dependency blocks only its dependents, listed in `waiting_on`. Nothing is substituted.

**Production status:** `paused` or `cancelled` if set; `running` if something can run or is running; `waiting_review` if nothing can, and something is `pending_review`; `needs_action` if nothing can, nothing awaits review, and something is `rejected` or `failed`, with `next_action` naming the Item; `complete` only when every Item is approved.

## 7. Failures and resume

Uses base spec 6.5 classes unchanged.

| Class | Production behaviour |
|---|---|
| Stop for owner | `paused` with reason, Chrome forward. A Take not yet at `submitted` is `aborted` and its Item returns to its prior state. Resume through `flow_job_control` |
| Stop run | The same. Planned Items stay planned. A quota stop resumes the next day |
| This job only | Item `failed`, others continue, next_action says modify the prompt or regenerate |
| Retry safely | Worker handles it within the Take, no new Take |
| Retry with spend | `max_generation_retries`: Animations 0, Images 1, inside the Take. Every attempt's quote counts |
| Caller fix | Refused at plan or call time |

A wrong count, ratio, duration or audio check is `RESULT_MISMATCH`: files kept, Item `failed`, never `pending_review`.

**New codes**, all Caller fix: `PROMPT_FILE_INVALID`, `ANALYSIS_REQUIRED`, `PLAN_CHANGED`, `PRODUCTION_NOT_FOUND`, `ITEM_NOT_FOUND`, `REVIEW_CONFLICT`.

**Idempotency:** a Take is recorded before its job is queued, with key `prod:<id>:<item>:take:<n>`, derived from intent. Repeating a key returns the same job (Task 5).

| Crash point | On restart |
|---|---|
| Before Take recorded | Item is `planned`, runs normally |
| Take recorded, job not queued | Same key queues it once |
| Job before `submitted` | Task 5 resumes it |
| Job at or past `submitted` | Task 11 reconcile downloads the result, or the Take fails with `credits_at_risk`. **Never resubmitted** |
| Job finished, Production not updated | Recovery reads the job by key and applies it |
| Download done, strip not done | Strip repeats from the original; no spend |

`flow_production_start` with the same `plan_id` and project returns the existing Production, unless `new_run: true` starts another. `flow_production_regenerate` checks in this order: a repeat matching the running Take's `of_take` and prompt returns that Take; any other call during `regenerating` is `REVIEW_CONFLICT`; an `expected_take` that isn't the latest Take is `REVIEW_CONFLICT`; otherwise it starts a new Take.

## 8. Flow synchronisation

Start runs a preflight before any spend: `flow_doctor`, the account check, balance read, and FFmpeg if there are Animations. Then per job, the base plan's mechanisms: direct composer asserted, settings read back, quote gate, tile observation with `source: flow`, asset-info check of the model, download, verify. Added here: ingredient chips counted before Start, and balance before and after in the report. A balance difference from the ledger is a warning, since refunds lag up to an hour.

## 9. Rulings on the conflicts

Each: decision, why, cost if wrong.

> **Amended 2026-11-03:** the owner's Contact Sheet contract supersedes R1's colours: approved and rejected use the red marker, rose means failed only, amber means live only.

**R1. Frozen UI vs review in the app.** *No new page, panel, column or button. Review lives in the existing table on `flow_image` (References, Stills) and `flow_video` (Animations).* The owner's request overrides the freeze for exactly this list:

| Existing part | Change for production rows only |
|---|---|
| Context menu | Adds `Approve`, `Reject`; `Retry` becomes "Retry with same prompt"; `Edit…` becomes "Modify prompt and regenerate…". `Remove` disabled. Character and scene submenus hidden |
| Keyboard | `Ctrl+Return` approves selected rows, shown in the menu |
| Status cell | Text `Review v2`, `Approved v2`, `Rejected`, `Regenerating`; existing colours only (amber, green, red, blue). Stale gets a tooltip line |
| Prompt cell | Shows `IMG_01 · prompt`; not inline-editable, so a prompt can't change without a regeneration. The dialog edits the raw prompt |
| Output cell | Unchanged: thumbnail, double-click opens the file in the system viewer. For video that's the silent copy |
| Progress cell | Unchanged, except a rejected row's bar is red via one shared colour helper |
| Character cell | Shows the Cast names |
| Banner label (existing `banner_label`) | Adds one line: `Zombie Bunker: references 4/4 · stills 6/8 · animations 0/8 · 14 of 60 credits · waiting for your review` |
| Existing buttons | `Retry failed` routes failed production rows to regeneration. `Start`, `Clear` and `Remove` leave them alone |
| Existing message box | Confirms an Animation regeneration's cost |

*Why:* a table row already is one reviewable thing with thumbnail, status and menu. This is an operate surface, so known patterns win. Impeccable's context step ran and confirmed there's no PRODUCT.md or DESIGN.md to answer to, so this rests on the incumbent code; no render critique is possible until Y7 builds it. *Cost if wrong:* reviewing 60 rows through a 56px thumbnail and an external viewer is slow. The fix is an inline preview in the overhaul brief, with no data changes.

**R2. Stitcher and later audio.** Named **Phase L**, not deleted.

| Base plan item | Now |
|---|---|
| Task 18 whole, including `stitch_video`, `last_frame` tool, `pythonPath` | L1 |
| Task 16: character voice row, `src/ui/characters/page.py`, `src/characters/voices.py` changes; Task 12's `preview_voice` return | L2 |
| Task 17 (local models) | Remains optional, Phase L |
| Task 19: stitch, music and assembled-video tests | L3, with final assembly |
| Task 20: "narration and music assembled" eval | L3 |
| Tasks 15 and 16 API tools, keys tab, key push | **In scope, unchanged.** Owner enters keys |
| FFmpeg, `src/editor/{model,ffmpeg,subtitles,autoedit}.py`, `last_frame_cmd` | Stay, per Global Constraints |

**Tool list:** `stitch_video` isn't registered at all, since an agent shouldn't see a tool that can only fail. Task 8 pins base spec 6.4 minus `stitch_video`, and asserts it's absent. Each Y task adds its tools to the pinned list. Task 19's "none return `NOT_IMPLEMENTED`" stays, over that list. L1 registers `stitch_video` and flips the assertion. *Cost if wrong:* none; registering later is one line.

**R3. Silent output.** *The deliverable is the stripped copy, and it takes the normal name.* C11 stands (`ffmpeg -an -c copy`, original kept) but the original moves to `videos/_original/<stem>.flow.mp4`. Flow's setting stays off, since it doesn't work. Productions force silence, with no parameter to turn it off. Review, mirror, `flow_list_assets`, `flow_download` and Phase L only ever see the silent file; the original appears only in `detail: full`. **Proof:** ffprobe `-select_streams a` on the deliverable must list zero streams and the duration must match the original within 0.5s, or it's `RESULT_MISMATCH` with no review. `audio_streams: 0` goes in the Take, the manifest and the Y8 evidence, which uses the original as a control showing audio exists. *Why keep the original:* credits were spent, and a strip bug shouldn't lose the clip. *Cost if wrong:* small extra disk use.

**R4. References in Flow.** *Primary: the approved Reference Sheet is uploaded as an ingredient image with a unique filename, then reused by filename per Shot. Fallback: a Flow Character created from the same approved sheet, chosen per Production as `reference_mode`. Never both.*

| Option | Evidence | Verdict |
|---|---|---|
| Image ingredient by file | Ran 12 of 12 with consistent faces (Phase 12 zombie test); search-then-upload exists in `addReference`; direct composer chip seen in the spike | **Primary** |
| Flow Character | Worked on 2026-10-24 through the agent composer (`docs/05`), free from one image. Save flow unrun in direct mode; video unknown | **Fallback, spike first** |
| Generated tile picked in the picker | Titles repeat, so no identity | Rejected |
| Both | Two chips for one person, using up slots, with no evidence of gain | Rejected |

**Identity:** generated titles aren't unique, so the approved file name is the identity: `assetName(seq, "<prodShort>-<itemId>", n, ext, dir)`. This also pins the exact Take in Flow, so a regenerated sheet can't be confused with the old one.

**Per Shot:**
- *Still or sheet-using job:* the picker's search looks for the filename, and uploads through the file chooser only if absent, then adds it. The engine counts ready chips (`aria-busy` false) against `refs` before Start, and any mismatch fails with no spend.
- *Animation with start frame:* Frames mode, Start chip takes the approved Still by the same method. Modes are exclusive radios, so no References are attached; the Still already carries identity.
- *Animation with no start frame:* Ingredients mode with its References, Omni or Veo Lite/Fast at 8s. Task 6 rejects other mixes.

**Cross-project:** the local file is the truth, so another Production's Approved Take is reused via `reuse: {production_id, item}` on a Reference or a Still. At start, the orchestrator checks the source (`PRODUCTION_NOT_FOUND`, `ITEM_NOT_FOUND`, or `REVIEW_CONFLICT` if it has no Approved Take), copies the file, records its sha256 and starts it `approved`. The file uploads to the new Flow project when first attached. Reuse costs no generation and doesn't need Flow's project switcher. This also lets a stills-first Production go on to Animations without remaking its Stills. Flow's own cross-project paste doesn't work (`docs/05`).

**Spike Y0** runs before Task 5, images only by default, and answers:
1. Does a multi-view sheet as ingredient keep identity, or does its grid layout leak into results?
2. Does the Create character save path work, and does its chip work in direct mode?
3. What's the ingredient limit per mode?
4. Do upload-by-name Start frames and Omni ingredients work? This needs video: at most 15 credits, the unspent part of the owner's 40 spike cap, **only if the owner agrees**.

*Decision rule set in advance:* the primary stays unless Y0 shows grid leak or lost identity in both sample Shots. Then try a single-view portrait as the ingredient; if still bad, make `character` the default. *Cost if wrong:* a config default and a re-run of free images.

**R5. Budget.** *One cap per Production, covering everything including regenerations and automatic retries.*

Credits assume Omni at quoted prices; 20% is a regeneration allowance, not a measurement.

| Production | Refs, Stills | Animations | Omni 360p 4s | Omni 720p 4s | Omni 720p 6s | Veo Lite 8s | 720p 6s + 20% |
|---|---|---|---|---|---|---|---|
| Sample size | 4, 8 | 8 | 32 | 56 | 80 | 80 | 96 |
| Typical | 5, 30 | 30 | 120 | 210 | 300 | 300 | 360 |
| Long | 6, 60 | 60 | 240 | 420 | 600 | 600 | 720 |
| Stills only | 5, 30 | 0 | 0 | 0 | 0 | 0 | 0 |

The month gives 1,000 credits with no rollover, plus 50 a day. A long Production nearly uses a month. Veo Lite gives 8s for 10, cheaper than Omni's 12 at 8s, but only at 8s.

Rules:
- **Start:** Animations mean `max_credits` is required, and the base default of 30 doesn't apply. The planned estimate must fit, and fit the live balance; otherwise `BUDGET_EXCEEDED` before any browser spend, with the amount in `details`. No partial start.
- **Per job:** Flow's quote is the gate, with the job's limit set to `min(item estimate, max_credits - spent)`. A quote above the estimate stops the Production (`quote_drift`): the price table is out of date. `resume` with `accept_quote: true` records the quote as the new estimate. A quote that fits the estimate but not the cap stops it too, cleared by `set_budget`. Both spend nothing, and abort the Take.
- **Spent** adds every quote at `submitted`. Refunds aren't credited back automatically, since they lag; raising the cap is an explicit act.
- **Regeneration:** Images use quota only and need no confirmation. An Animation must fit `max_credits - spent - planned estimates`, so a regeneration can't eat the budget of Items not yet made. `dry_run: true` returns the cost. The app confirms the cost, and offers to raise the cap in the same box. Agents use `flow_job_control {action: 'set_budget'}`.
- **The 300 acceptance cap** is for tests, not real work. A real Production spends only what its own `max_credits` allows. **Proposed:** Y8 and Y9 take at most 60 credits from inside the 300, which the Phase L deferral frees. This is an owner checkpoint, not assumed.

*Cost if wrong:* a too-low cap pauses a run with nothing lost.

## 10. Other rulings

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R6 | References gate is on by default: one stop for review after sheets | A bad sheet ruins every Still. It's the only forced stop in a stills-only run. `gates.references: false` runs unattended | Overnight runs stop early unless the flag is set |
| R7 | Stills gate on by default for Animations | That gate is what stands between review and credits | Same |
| R8 | The shim forces `actor: 'agent'`; the app sends `app`. Agents *can* approve, as asked, but the guide says only when told | Keeps the owner in control and auditable | An agent could self-approve; the record shows it |
| R9 | Rows and review truth live in `production.json`; the app only displays them and sends actions | One writer | App can't review with the engine down, but it starts the engine on demand |
| R10 | One queued job at a time per Production | Priority by stage, simple cancel and resume | None at one-at-a-time pacing |
| R11 | Animation defaults: Omni 1.1 Flash 720p 6s | The owner's earlier preference for Omni. Explicit columns override | Pacing differs from what was wanted; re-plan is free |
| R12 | Stale is a flag, with no automatic cascade | "Must not affect other approved images" | Owner must decide on each stale item |
| R13 | Production's Flow project is new unless `project_url` is given | Keeps the picker clean and names unique | None |

## 11. Tools

All are `flow_production_*`. Control reuses `flow_job_control` (`pause`, `resume`, `cancel`, new `set_budget`) and `flow_wait` on `run_id`. `retry_failed` on a production run regenerates failed Items with their current prompts.

| Tool | Input | Output (concise) | Annotations |
|---|---|---|---|
| `flow_production_plan` | `folder` or `moodboard_path`, `prompts_path`; or `plan`; `overrides`, `defaults`, `name` | Report (section 4) | readOnly, idempotent |
| `flow_production_start` | `plan_id`, `cast_confirmed`, `auto_confirm`, `max_credits`, `project_url`, `output_root`, `gates`, `reference_mode`, `new_run` | `production_id, run_id, status, next_action` | not readOnly, not destructive, idempotent, openWorld |
| `flow_production_status` | `production_id` or latest; `stage`, `state`, `detail`, `cursor`, `limit` | `status`, per-stage counts, credits, `waiting_on`, `next_action`; items only when filtered, paged | readOnly, idempotent |
| `flow_production_review` | `production_id`, `items: [{id, take}]`, `action: approve or reject`, `note` | Item states, counts, Stale list | not readOnly, not destructive, idempotent, closed world |
| `flow_production_regenerate` | `production_id`, `item`, `prompt`, `expected_take`, `auto_confirm`, `dry_run` | `take, job_id, state, estimated_credits` | not readOnly, not destructive, idempotent with `expected_take`, openWorld |

Retry is `regenerate` with no `prompt`, Modify is with one. Concise output for 300 Items stays under 2,000 tokens. Errors follow base spec 6.5, and `next_action` names the next tool to call. `flow_job_control` gains `set_budget` and `resume`'s `accept_quote`. `overrides` shape: `{references: [{id, kind, name, sheet_prompt, reuse}], shots: {<id>: {refs, start, reuse}}}`, where listing `references` replaces rows of the same ID, and `split_from: <id>` adds a Reference that replaces the named row.

## 12. Progress, app, seams, evals

**Live progress:** new events through the existing `appendEvent` and `/events`: `production.item` (`production_id, item, stage, state, take, prompt, file, ref_names, stale, error, progress, source`) and `production.summary`. Item percentages come only from Flow; stage figures are counts. `flow_wait` on a production's run adds the summary, which also feeds MCP progress when a token is sent.

**App:** `RunMirror` (Task 14) adds rows from these events, one per Item, with `origin='agent'` and new `Job` fields. At app start it calls `flow_production_status` with `detail: full` for each production run, then follows events from there. Mapping to `JobStatus`, so `StatsHeader` and existing code keep working:

| Item state | `JobStatus` | `Job.review` |
|---|---|---|
| `planned` | `QUEUED` | `""` |
| `generating` | `RUNNING` | `""` |
| `pending_review`, `approved`, `rejected` | `DONE` | same |
| `regenerating` | `RUNNING` | `regenerating` |
| `failed` | `FAILED` | `""` |

`QUEUED`, not `PENDING`, so `Start` can never submit them. Paused Productions show in the banner.

**Module seams:** `parse.js` and `plan.js` (text to plan, pure apart from reading files), `state.js` (reducer and `nextItem`, pure, the deep core), `compose.js` (Take to job spec, pure), `store.js` (durability), `orchestrator.js` (the only module tools call). Flow knowledge stays in `src/flow/`. Tests cross these interfaces; only the orchestrator needs fake Flow.

**Cold-agent evals (Y9), agent given only the MCP and a folder:** stills-only zombie sample starts no video; a mixed folder; a row hiding two people gets split; prose-only file gets normalised; a budget too low is refused and reported; owner says "approve 1-4, redo 5 with a darker mood" and only those change; a crash mid-run resumes without a second Start; "continue yesterday's". Score completion, calls, wrong calls, unapproved spend. Target 100% on the first two and at least 90% overall, with no unapproved spend or self-approval.

**Not used:** `error-handling-patterns` (base spec 6.5 already fixes the classes), `codebase-memory-mcp` (Grep answered the callers in this small area).

## 13. Owner decisions

Execution stays stopped until the owner answers 1 and 2. The rest have working defaults.

1. **Resume and order:** approve section 14's order.
2. **Y0's video leg:** may it use up to 15 credits, the unused part of the 40 spike cap? If no, Y0 is images only and Y8 finds out the same facts later.
3. **Live budget:** Y8 and Y9, at most 60 credits inside the 300 cap.
4. **A real prompts-file sample:** the only sample has no animations, so shapes 2 and 3 in section 4 are the planner's guess. Anything else still works through the agent, just with more calls. A sample before Y1 replaces the guess.
5. **Check R6 and R7:** one review stop after sheets, and credits never spent on unreviewed Stills, is the planner's reading of "minimise intervention while keeping control".
6. **Keys:** Fish and Stability keys at Tasks 15 and 16, as already planned. Stability's free 25 credits cover about 3 tracks (C4).

## 14. Overall order

Tasks 1-4 (done) → **Y0** → 5, 6, 7, 8 → 9, 10, 11 → **Y1-Y5** → 12, 13, 14 → **Y6, Y7** → 15, 16 (reduced) → **Y8** → 19 (reduced) → **Y9** → 20 → later **Phase L** on the owner's word.

## 15. Unverified

Everything Y0 asks; the failed-tile display; Omni ingredient limits; sheet layout's effect on video; how `Clear prompt on submit` and chips behave between direct jobs (Y3 tests it on fake Flow, Y8 live); real prompts-file formats (decision 4).
