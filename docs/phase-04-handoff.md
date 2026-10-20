# Phase 4 handoff — Flow Video on the Gemini API (done 2026-10-20)

## State
- Everything in `docs/phase-04-gemini-video.md` is built. `pytest`: 91 passed (61 before, 30 new). All HTTP in tests goes through `httpx.MockTransport` with a fake clock, so nothing sleeps and no live call has been made.
- `python run.py` → **Flow Video** is now a `GeneratorPage` driven by `GeminiVideoProvider` (`src/gen/gemini_video.py`). The banner says it uses the user's key, that clips cost credits and carry SynthID, and that Veo 3.1 Preview isn't offered. With no key, each row fails before any request, and the Output cell shows "No Gemini API key. Add one in Settings → API keys."
- Real-window screenshot (Windows 11, key source forced empty, network blocked): `D:\tmp_render\phase4\phase4_flow_video.png`. The script (patches `keys.get_key` to `""` and `httpx.Client.send` to raise) changed no page settings, and `%APPDATA%\LabsStudio\settings.json` kept its old timestamp.
- No new deps.

## Deviation from the plan row ("Video page (Veo)")
The Gemini API docs (checked 2026-10-20) say the Veo 3.1 Preview models (`veo-3.1-generate-preview`, `-fast-`, `-lite-`) **shut down on October 22, 2026**. Veo 3.0 is already deprecated, and the docs point to **Gemini Omni Flash** (`gemini-omni-1.1-flash`). The user has no key yet, so a `predictLongRunning` Veo client would be dead before its first run. The page targets Omni Flash through the **Interactions API**, the same way Phase 3 dropped Imagen. The Veo GA models only exist on the Gemini Enterprise Agent Platform (Vertex auth), which is out of scope.

What maps where:
- t2v → text `input`. i2v start / start + end → 1–2 `image` items before the text (refs sorted by name: first = start, second = end). Subject references → `task=reference_to_video`, up to 3.
- duration → Omni has **no duration parameter**, since length (3–10 s) comes from the prompt. The `duration` field appends "Make the clip about N seconds long." `auto` leaves the prompt alone.
- resolution 360p/720p/1080p/4k and aspect 16:9 / 9:16 → `response_format`.
- long-running polling → `background: true` + `GET interactions/{id}`, cancel on Stop via `POST interactions/{id}/cancel`.
- download → inline base64 `data`, or a `uri` fetched with the key header. Redirects are followed by hand, and the key is sent only to the API host.

## Unverified until the first real run (no key yet)
1. **Background mode for Omni.** The Omni page shows only synchronous calls. `background`, `/cancel` and the statuses come from the general Interactions reference. The provider copes either way: a terminal reply to the POST is parsed straight away, and a 400 that names `background` triggers one synchronous resend with the job timeout.
2. **Failed-interaction shape** (`errors[{code,message}]`) and how safety blocks are worded. Policy detection is a word-boundary regex (`safety|policy|blocked|prohibited|rai|filtered|responsible ai`) over the message, code and any model text.
3. **Reference cap of 3** and the `task` values come from the docs. Nothing has confirmed them live.
4. Expected run time (120 s, used only for the progress bar).

## Layout
- `src/gen/gemini_video.py`: `GeminiVideoProvider(key_source, transport, api_base, sleep, clock)`, `build_request`, `parse_interaction`. It reuses Phase 3's `encode_ref`, `map_http_error`, `KEY_ID` and `_no_key_message` from `gemini_image.py`.
- `src/app.py` `register_pages`: `flow_video` → `GeneratorPage("flow_video", GeminiVideoProvider(), banner=tr("omni_banner"))`.
- `src/ui/generator/prompt_model.py`: `VIDEO_EXTS` + `video_placeholder()`, a drawn 16:9 film tile with a play triangle, so `.mp4/.webm/.mov` rows don't try to decode the file each paint. A first-frame thumbnail would need QtMultimedia's async decoder, so it was skipped.
- `src/languages/en.py`: `gen_resolution`, `gen_duration`, `gen_video_task`, `gen_poll_interval`, `gen_job_timeout`, `vid_duration_*`, `vid_task_*`, `omni_banner`.
- `tests/test_gemini_video.py`: the new tests.

## Behaviour notes
- Poll interval: config field (10 s default). The wait is sliced into 0.5 s steps that check `should_stop()`. The job timeout (600 s default) covers submit + poll. On timeout the provider cancels and raises a **non-retryable** error, because a resubmit would bill again.
- Poll hiccups (429/5xx/network) are tolerated 3 times in a row, then the job fails with a non-retryable error for the same billing reason. Submit-time 429/5xx/network errors stay retryable, so the queue's auto-retry resubmits.
- `count` = N sequential interactions per row. Videos are held in memory until `save_outputs` writes them. That's fine for 3–10 s clips, but 4k output may be large.
- `store: true` is sent, which background mode needs. Google keeps the interaction (and makes multi-turn edits possible). Nothing in the app uses edits yet.

## Next
- When the user adds a key: one real t2v row and one start+end row, then check items 1–2 above in the log.
- Phase 5 per `docs/02-phase-plan.md`.
- Optional: video editing/extension (`previous_interaction_id`), an `LABS_STUDIO_DATA` env override in `config.app_data_dir()` (Phase 3 note).
