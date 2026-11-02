# Labs Studio: Agent Control Testing Guide

Tests for the google-flow MCP as it is now: the tool list in `mcp/google-flow/src/shim/tools.js`, the model facts in `mcp/google-flow/config/capabilities.json` (verified 2026-11-02). The automated version of sections 1-16, 18 and 19 is `tests/live/run_acceptance.mjs`; this guide is the manual and reference form. Test IDs match the script.

## Ground rules

- Pass means a file exists on disk, has size above 0 and starts with the right magic bytes. A status string such as `done` or `ready_for_confirmation` is never the assertion for a generation test. Refusal tests assert the exact `error_code`.
- Generation: `flow_generate_image` and `flow_generate_video` without `auto_confirm` are free dry runs (no browser) and return `status: ready_for_confirmation` plus an estimate. With `auto_confirm: true` they return `job_id` and `run_id` at once; loop `flow_wait` until `finished` is true, then read `outputs[].file` from the final reply (or `flow_list_assets` with `run_id`).
- Always pass `max_credits` with `auto_confirm: true`. Pass `idempotency_key` when a retry is possible.
- Failures carry `error_code`, `retryable`, `credits_at_risk`, `next_action`. Do what `next_action` says. Never try to get past a CAPTCHA, verification or a limit: stop and tell the owner.
- A test project is any project you created in the test. `flow_delete_project` with `confirm: true` only on such a project.

### Magic bytes

| Type | Starts with |
|---|---|
| JPEG | `FF D8 FF` |
| PNG | `89 50 4E 47` |
| MP4 | `ftyp` at bytes 4-8 |
| MP3 | `ID3`, or `FF Ex`/`FF Fx` frame sync |
| WAV | `RIFF` ... `WAVE` at bytes 8-12 |

### Credit column

"0" means free: quota only (images on banana21/banana2Lite/bananaPro cost 0 credits and count against daily limits of 1000/1000/100; 2K upscales have their own 200/day), or no spend at all (dry runs, reads). Video credits come from `capabilities.json`: Omni 360p 4s = 4, 360p 6s = 5, 720p 4s = 7, 720p 8s = 12; Veo Lite 10, Veo Fast 20, Veo Quality 100 (720p, 8s only). Fish voice on `s2.1-pro-free` costs 0; every other voice model costs money. Stable Audio costs 8 Stability credits per call (not Flow credits).

### Prerequisites

- Chrome profile for Flow signed in. `FLOW_DATA_DIR` set if you want an isolated engine state. `FISH_API_KEY` for section 12. ffmpeg on PATH for sections 11 and 19.
- A target Flow project URL (`FLOW_TEST_PROJECT` in the script).
- Budget stop: end the session if the balance (`flow_status.balance`) drops by 60 from where you started.

## Table of Contents

1. Connection and status
2. Simple image generation
3. Models
4. Aspect ratios
5. Size and count
6. Reference images (ingredients)
7. Project management
8. Characters
9. Scenes
10. Characters and scenes in generation
11. Video
12. Audio
13. Batch
14. Cross-project
15. Diagnostics and assets
16. Errors and edge cases
17. Productions (plan free; start is manual)
18. Stress and boundaries
19. Last frame and stitch
- Reference: tools, models, ratios, issue template

---

## 1. Connection and Status

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-1.1 | `flow_connect {}` | 0 | `status` is `connected` and `account` is the expected address. |
| T-1.2 | `flow_status {}` | 0 | `browser` true, `flowAccessible` true, `balance` is a number, `queue` present. |
| T-1.3 | `flow_status { full: true }` | 0 | `screenshot` path exists, is PNG/JPEG, size above 0. |
| T-1.4 | `flow_status {}` | 0 | `account` equals `expectedAccount` when set; `accountStatus` is not `unverified`. |
| T-1.5 | `flow_disconnect {}` then `flow_connect {}` | 0 | Second call returns `connected`; the Chrome window stayed open throughout. |

Agent prompt for T-1.1: "Connect to Google Flow and tell me which account is signed in."

---

## 2. Simple Image Generation

Default model banana21, 16:9, 1K, count 1. Prompts are examples; the point is the file.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-2.1 | `flow_generate_image { prompt: "blue butterfly", project_url }` (no auto_confirm) | 0 | `status` is `ready_for_confirmation`, no `job_id` returned, `estimate` present. No new file appears in the run folder. |
| T-2.2 | Same with `auto_confirm: true, max_credits: 1`, then `flow_wait` loop | 0 | Job `done`; `outputs[0].file` exists, size above 0, JPEG or PNG. |
| T-2.3 | One-word prompt `"chaos"`, auto_confirm | 0 | As T-2.2. |
| T-2.4 | Prompt with brackets, quotes, `<b>`, Japanese text, dry run | 0 | `ready_for_confirmation` and `request.prompt` preserves the characters. |
| T-2.5 | Medium (about 30 words) and long (about 200 words) prompts, auto_confirm | 0 | Each produces a valid image file. |
| T-2.6 | `output_root` set to a scratch folder, auto_confirm | 0 | File lives under that folder, valid image. |

Note: a custom filename is not an input any more; the engine names files by sequence and prompt inside the run folder.

---

## 3. Model Variations

Real names: `banana21` (Nano Banana 2.1, default), `bananaPro`, `banana2Lite`. Aliases like "Nano Banana 2" are not accepted; they return `MODEL_NOT_AVAILABLE` (see T-16.2).

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-3.1 | `model: "banana21"`, auto_confirm | 0 | Valid image file. |
| T-3.2 | `model: "bananaPro"`, one image only (100/day quota) | 0 | Valid image file. |
| T-3.3 | `model: "banana2Lite"`, one image | 0 | Valid image file. |
| T-3.4 | `flow_estimate { jobs: [one per model] }` | 0 | Reply has an estimate per job; credits 0 for images. |
| T-3.5 | Same prompt on all three models, compare | 0 | Three valid files, three different paths. Visual comparison is manual. |

---

## 4. Aspect Ratio Variations

Valid: `16:9`, `4:3`, `1:1`, `3:4`, `9:16`.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-4.1 | `ratio: "9:16"`, auto_confirm | 0 | Valid image file; decoded height greater than width (check with any image tool). |
| T-4.2 | Dry run for each of the five ratios | 0 | Each returns `ready_for_confirmation` and `request.ratio` equal to the one sent. |
| T-4.3 | Real run at `1:1` | 0 | Valid image, width equals height. |
| T-4.4 | Real runs at `4:3` and `3:4` (optional, quota only) | 0 | Valid images, orientations match. |

---

## 5. Size and Count

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-5.1 | `size: "2K"`, auto_confirm | 0 | Valid image; larger than the 1K file of the same prompt (pixels or bytes). Uses the 2K daily quota. |
| T-5.2 | `count: 2`, auto_confirm | 0 | `outputs` has exactly 2 entries, both valid image files, distinct paths. |
| T-5.3 | `count: 4, size: "2K"`, dry run | 0 | `ready_for_confirmation` with an estimate that accounts for 4 images. |
| T-5.4 | `count: 4`, auto_confirm | 0 | Exactly 4 valid files. |
| T-5.5 | All options together: model, ratio, size, count 2 | 0 | 2 valid files. |

---

## 6. Reference Images (ingredients)

`ingredients` takes file paths, or objects naming a file, character, scene or project.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-6.1 | `ingredients: [<path of an earlier output>]`, auto_confirm | 0 | The input path exists and is valid; the output is a new, different valid image file. |
| T-6.2 | Two paths in `ingredients` | 0 | Valid output image. |
| T-6.3 | Ingredient plus `model: "bananaPro"`, `ratio: "1:1"` | 0 | Valid output image. |

---

## 7. Project Management

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-7.1 | `flow_list_projects {}` | 0 | List contains the target project's id. |
| T-7.2 | `flow_open_project { url, create_if_missing: false }` | 0 | Returns that URL. |
| T-7.3 | `flow_open_project { name: "acceptance-<stamp>" }`, then `flow_list_projects { query }` | 0 | A new URL differing from the target, and it is listed. Record it as script-created. |
| T-7.4 | `flow_rename_project { url, name }`, then list with the new name | 0 | Listed under the new name. |
| T-7.5 | `flow_delete_project { url }` with no confirm | 0 | `error_code` `INVALID_PARAMS`; project still listed. |
| T-7.6 | `flow_delete_project { url, confirm: true }` on the project from T-7.3 only | 0 | Project no longer listed. |
| T-7.7 | `flow_generate_image` with `project_url` set, auto_confirm | 0 | Valid image file; its run's `flowProjectUrl` is that project. |
| T-7.8 | `flow_generate_image` with `project_name` of an existing project | 0 | Valid image; no duplicate project created (list count unchanged). |

Never run T-7.6 against a project you did not create.

---

## 8. Character System

`flow_create_character` is free from an image. With only a `prompt` Flow generates a portrait, which spends, and it needs `auto_confirm: true`.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-8.1 | `{ project_url, name, images: [<valid image path>] }` | 0 | Source image exists and is valid; call succeeds. |
| T-8.2 | `flow_list_characters { project_url, details: true }` | 0 | Name from T-8.1 is listed. |
| T-8.3 | `{ name, prompt }` with `auto_confirm: false` | 0 | Name is not in the list afterwards (nothing was spent or created). |
| T-8.4 | `{ name, prompt }` with `auto_confirm: true` (manual only, spends) | Varies | Character listed; run only on the owner's say-so. |
| T-8.5 | `flow_import_character { project_url, from_project_url, name }` | 0 | Character listed in the destination (see T-14.1). |
| T-8.6 | Generate with `ingredients: [{ character: "<name>" }]` | 0 | Valid image file. |
| T-8.7 | Two characters in `ingredients` | 0 | Valid image file. |

---

## 9. Scene System

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-9.1 | `flow_create_scene { project_url, name, images: [<valid image>] }` | 0 | Source valid; call succeeds. |
| T-9.2 | `flow_list_scenes { project_url }` | 0 | Scene name listed. |
| T-9.3 | `flow_create_scene` with prompt only, `auto_confirm: true` (manual only) | Varies | Scene listed. |

---

## 10. Characters and Scenes in Generation

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-10.1 | `ingredients: [{ character }, { scene }]`, auto_confirm | 0 | Valid image file. |
| T-10.2 | Two characters plus a scene | 0 | Valid image file. |
| T-10.3 | Character, scene, a file path, `bananaPro`, `count: 2` | 0 | 2 valid files. |

---

## 11. Video

Models: `omni` (default), `veoLite`, `veoFast`, `veoQuality`. Omni takes 4, 6, 8 or 10 seconds and 360p or 720p; Veo takes only 8 s at 720p. Modes by model are in `capabilities.json`. Use Omni 360p 4s `silent: true` for tests: 4 credits.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-11.1 | `flow_generate_video { prompt, model: "omni", resolution: "360p", duration: 4, silent: true }` no auto_confirm | 0 | `ready_for_confirmation`, estimate about 4 credits. |
| T-11.2 | Same with `auto_confirm: true, max_credits: 5`, `flow_wait` loop | 4 | `outputs` has one file; exists, size above 0, MP4 (`ftyp`). |
| T-11.3 | `ratio: "9:16"` Omni 360p 4s (manual, spends) | 4 | Valid MP4. |
| T-11.4 | `start_frame: <image path>` Omni 360p 4s (manual) | 4 | Valid MP4; input image valid. |
| T-11.5 | `veoLite` 720p 8s (manual, spends) | 10 | Valid MP4. |
| T-11.6 | `veoQuality`, `veoFast` | 100, 20 | Do not run in acceptance. Dry run only: estimate matches the table above. |

Cap acceptance runs at three clips in total.

---

## 12. Audio

Replaces the old Grid Architect section, which has no tool now.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-12.1 | `audio_voice_list { limit: 3 }` | 0 | Non-empty `voices`, each with `voice_id`. |
| T-12.2 | `audio_voice_generate { text, model: "s2.1-pro-free", format: "mp3" }` | 0 | `file` exists, size above 0, MP3 magic. |
| T-12.3 | `audio_stable_generate { kind: "sfx", prompt, duration: 2 }` without auto_confirm | 0 | Reply is an estimate only; no `file`. |
| T-12.4 | Same with `auto_confirm: true` (manual, 8 Stability credits) | 8 Stability | `file` is a valid WAV (or MP3 if requested). Not part of the automated run. |
| T-12.5 | `audio_voice_generate` with `model: "s2.1-pro"` | money | Do not run in acceptance; the free model must never be swapped for a paid one by itself. |

Missing key gives `MISSING_API_KEY`: that is an environment failure, not a code failure.

---

## 13. Batch

`flow_batch_start` takes `jobs` (or a `.json`/`.csv` `file`), `defaults`, `project`, `stop_on`.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-13.1 | 3 image jobs, no auto_confirm | 0 | Reply is an estimate; no `run_id`. |
| T-13.2 | 2 image jobs, `auto_confirm: true, max_credits: 1`, `flow_wait` on `run_id`, then `flow_job_status { run_id, detail: "full" }` | 0 | Two outputs in total; each exists, valid image. |
| T-13.3 | 10 image jobs from a `.csv` with a `prompt` column (manual) | 0 | 10 valid files across the run. |
| T-13.4 | Mid-run `flow_job_control { action: "pause", run_id }` then `resume` (manual) | 0 | Run completes after resume; all files valid. |
| T-13.5 | Failed job, then `flow_job_control { action: "retry_failed", run_id }` (manual) | may spend | Retry produces a valid file; credits_at_risk read first. |

---

## 14. Cross-Project

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-14.1 | Create temp project; `flow_import_character` from the target; `flow_list_characters` on temp; delete temp with confirm | 0 | Imported name listed; temp project gone afterwards. |
| T-14.2 | Generate in the temp project with the imported character | 0 | Valid image file. |

---

## 15. Diagnostics and Assets

`flow_discover_ui` no longer exists; `flow_doctor` checks the page against the UI contract.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-15.1 | `flow_doctor {}` | 0 | `ok` true, `missing` empty. |
| T-15.2 | `flow_capabilities {}` | 0 | `image.models` has the three names; `video.models.omni` present; `verifiedAt` is a date. |
| T-15.3 | `flow_screenshot { name }` | 0 | Returned path exists, valid PNG/JPEG. |
| T-15.4 | `flow_list_assets { run_id }` for an earlier run | 0 | Every `file` listed exists and is a valid image. |
| T-15.5 | `flow_list_runs { limit: 5 }` | 0 | At least one run with job counts. |
| T-15.6 | `flow_download { latest: true, project_url }` (manual) | 0 | A file is saved; it is valid. No new generation happened (balance unchanged). |
| T-15.7 | `flow_download { job_id }` for a finished job (manual) | 0 | File restored on disk, valid. |

---

## 16. Errors and Edge Cases

Every row asserts the `error_code` and that nothing was queued or spent.

| ID | Call | Credits | Expected `error_code` |
|---|---|---|---|
| T-16.1 | Empty/blank `prompt` | 0 | `INVALID_PARAMS` |
| T-16.2 | `model: "nope"` | 0 | `MODEL_NOT_AVAILABLE` |
| T-16.3 | `ratio: "7:5"` | 0 | `RATIO_NOT_AVAILABLE` |
| T-16.4 | `flow_open_project` with unknown URL, `create_if_missing: false` | 0 | `PROJECT_NOT_FOUND` |
| T-16.5 | `ingredients` with a path that does not exist | 0 | `INVALID_PARAMS` |
| T-16.6 | `count: 5` | 0 | `INVALID_PARAMS` |
| T-16.7 | Video, auto_confirm, `max_credits: 1` (estimate above cap) | 0 | `BUDGET_EXCEEDED` |
| T-16.8 | `flow_job_status { job_id: "missing" }` | 0 | `JOB_NOT_FOUND` |
| T-16.9 | `flow_delete_project` without confirm | 0 | `INVALID_PARAMS` |
| T-16.10 | Tab tool while a job is running | 0 | `JOB_IN_PROGRESS` (manual; `flow_status`, `flow_wait`, `flow_screenshot` still work) |
| T-16.11 | Tool call with Chrome closed | 0 | `BROWSER_NOT_CONNECTED` after `flow_disconnect` plus closing Chrome (manual) |
| T-16.12 | Prompt of 5000+ characters, dry run | 0 | Either accepted with a truncated `request.prompt`, or a clean error; no crash. Record which. |
| T-16.13 | Policy-violating prompt, auto_confirm (manual) | 0 | `GENERATION_REFUSED` or `SAFETY_BLOCKED`; no file. |
| T-16.14 | `size: "8K"`, `video duration: 7` | 0 | `COMBINATION_NOT_SUPPORTED` / `INVALID_PARAMS`; record the exact code. |

---

## 17. Productions

Productions turn a folder with a moodboard file and a prompts file into References, Stills and silent Animations, each waiting for review. Starting one spends credits with Animations, so it is manual and needs the owner's cap.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-17.1 | `flow_production_plan { folder }` | 0 | `plan_id`, parsed Cast and Shots, `estimate`. Free, no browser. |
| T-17.2 | Answer `analysis_needed` with `overrides`, plan again | 0 | Same `plan_id` family, no errors listed. |
| T-17.3 | `flow_production_start { plan_id, cast_confirmed: true, auto_confirm: true, max_credits }` (manual) | per estimate | Reference images exist on disk and are valid; status reaches `waiting_review`. |
| T-17.4 | `flow_production_status { detail: "full" }` | 0 | Items listed with Take files; each file exists. |
| T-17.5 | `flow_production_review` with named Takes (only when the owner said so) | 0 | Verdict recorded; a wrong Take number changes nothing and is named. |
| T-17.6 | `flow_production_regenerate { dry_run: true }` then `auto_confirm: true` with `expected_take` | per estimate | New Take file exists and is valid; a repeat with the same `expected_take` spends nothing. |

Never approve unasked.

---

## 18. Stress and Boundaries

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-18.1 | `flow_estimate` with 20 mixed image and video jobs | 0 | Total estimate returned; no job queued. |
| T-18.2 | Two identical `flow_generate_image` calls with one `idempotency_key`; `flow_status` while it runs; then `flow_wait` | 0 | Second reply has `repeated: true` and the same `job_id`; `flow_status` succeeds mid-run; final output is a valid image file; only one file produced. |
| T-18.3 | Five dry runs back to back | 0 | All `ready_for_confirmation`, no cross-talk. |
| T-18.4 | Two projects in one session (target and temp), image in each | 0 | Each run folder holds a valid image; the temp project is deleted afterwards. |
| T-18.5 | Everything at once: character, scene, file ingredient, `bananaPro`, `count: 4`, `2K` (manual) | 0 | 4 valid files. |

---

## 19. Last Frame and Stitch

Both are free and need ffmpeg.

| ID | Call | Credits | Asserts |
|---|---|---|---|
| T-19.1 | `last_frame { run_id, asset_id: <video job_id> }` | 0 | `file` exists, valid PNG. |
| T-19.2 | `stitch_video { run_id, auto: true }` | 0 | `file` exists, valid MP4; originals untouched. |
| T-19.3 | `stitch_video` with a `spec` (clips with trim, voice, bgm) (manual) | 0 | Valid MP4, duration roughly the sum of clips. |

---

## Reference: Tools

| Tool | Purpose | Credits |
|---|---|---|
| `flow_connect`, `flow_disconnect` | Attach/detach Flow Chrome | 0 |
| `flow_status`, `flow_doctor`, `flow_capabilities`, `flow_screenshot` | State, UI contract, facts | 0 |
| `flow_estimate` | Cost of planned jobs | 0 |
| `flow_generate_image` | Image job; dry run unless `auto_confirm` | quota |
| `flow_generate_video` | Video job | credits |
| `flow_batch_start` | Many jobs as one run | credits for video |
| `flow_production_plan/start/status/review/regenerate` | Productions | with Animations |
| `flow_job_status`, `flow_wait`, `flow_job_control`, `flow_list_runs` | Follow and steer jobs | 0 (retry may spend) |
| `flow_list_assets`, `flow_download` | Files of a run or project | 0 |
| `flow_open_project`, `flow_list_projects`, `flow_rename_project`, `flow_delete_project` | Projects | 0 |
| `flow_create_character`, `flow_list_characters`, `flow_import_character`, `flow_create_scene`, `flow_list_scenes` | Characters and places | image 0, prompt spends |
| `audio_voice_generate`, `audio_voice_list`, `audio_stable_generate` | Voice, music, effects | free voice model / 8 Stability |
| `stitch_video`, `last_frame` | Assemble and chain | 0 |

Gone with the old server: `flow_account_check`, `flow_discover_ui`, `flow_download_latest` (now `flow_download { latest: true }`), `flow_open_tools_gallery`, `flow_use_grid_architect`, `flow_use_tool`.

## Reference: Models and Ratios

| Kind | Names | Ratios |
|---|---|---|
| Image | `banana21` (default), `bananaPro`, `banana2Lite` | 16:9, 4:3, 1:1, 3:4, 9:16; sizes 1K, 2K; count 1-4 |
| Video | `omni` (default), `veoLite`, `veoFast`, `veoQuality` | 16:9, 9:16; count 1-4 |
| Voice | `s2.1-pro-free` (default, free), `s2.1-pro`, `s2-pro`, `s1`, `drama-3` | not applicable |

## Issue Tracking Template

| Issue # | Test ID | MCP Tool | Severity | Description | Expected vs Actual |
|---|---|---|---|---|---|
| | | | Critical/Major/Minor | | |
