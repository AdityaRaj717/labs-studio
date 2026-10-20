# Phase 5 handoff: OpenAI Image and Grok pages (done 2026-10-21)

## State
- Everything in `docs/phase-05-openai-grok.md` is built.
- `pytest`: 138 passed (91 before, 47 new). All HTTP in tests goes through `httpx.MockTransport`, with a fake clock for video polling. No live call has been made, because there are no OpenAI or xAI keys yet.
- `python run.py` → the sidebar entries **OpenAI Image** (`openai_image`) and **Grok Imagen** (`grok`) are real `GeneratorPage`s now. With no key, each row fails before any request, and the Output cell shows "No OpenAI API key…" or "No xAI API key…".
- **Settings → API keys** has three rows: Gemini, OpenAI, xAI. Each has its own "get a key" link.
- Screenshots (Windows 11, dark, key source forced empty, network blocked): `D:\tmp_render\phase5\phase5_grok.png`, `phase5_openai.png`, `phase5_settings.png`. The smoke script closed the window normally, so `%APPDATA%\LabsStudio\settings.json` got the usual close-time save (geometry and last page).
- No new deps.

## Layout
- `src/gen/http_common.py`: shared `send` / `json_body` / `error_info` / `map_http_error(resp, who)` / `download` for OpenAI-style and xAI-style error bodies. Gemini still uses its own `map_http_error`.
- `src/gen/openai_image.py`: `OpenAIImageProvider(key_source, transport, api_base)`, `build_params`, `build_request` (JSON for generations, multipart `image[]` for edits), `parse_response`.
- `src/gen/grok.py`: `GrokProvider(key_source, transport, api_base, sleep, clock)`, `build_image_request`, `build_video_request`, module-level `parse_video`, `data_uri`.
- `src/ui/pages/settings_page.py`: `KEY_PROVIDERS` tuples gained a 4th item (the link text key). `KeyRow(..., link_key=...)`.
- `src/app.py` `register_pages`: `grok` and `openai_image`.
- `src/languages/en.py`: `keys_openai`, `keys_xai`, `keys_get_key_openai`, `keys_get_key_xai`, `gen_size`, `gen_quality`, `gen_output_format`, `gen_background`, `gen_moderation`, `oai_bg_*`, `oai_mod_*`, `openai_banner`, `gen_mode`, `grok_mode_*`, `gen_image_model`, `gen_video_model`, `gen_image_resolution`, `gen_image_quality`, `gen_video_resolution`, `gen_video_seconds`, `gen_video_audio`, `gen_video_refs`, `grok_refs_*`, `grok_banner`.

## Unverified until the first real run
1. **Model IDs.** `gpt-image-2.5-flare` / `-sunburst` and `grok-imagine-image-2.0` / `grok-imagine-video-1.5(-lite)` come from the 2026-10-20 docs pages. Edit `MODELS`, `IMAGE_MODELS` and `VIDEO_MODELS` if any is refused.
2. **OpenAI edits field name.** The multipart field is `image[]`, as in the curl docs example. If the API answers 400 about `image`, switch it to `image`.
3. **xAI error body shape.** Both `{"error": "…", "code": "…"}` and `{"error": {"message", "code"}}` are handled. Policy detection is a word regex over the message and code.
4. **xAI video poll** HTTP code for pending (200 or 202, both accepted) and whether `progress` is present. Status values outside `done/failed/expired` are treated as pending.
5. **xAI `n` on edits** and the 5-image edit cap (the guide says "up to 5"; the REST schema states no max).
6. **OpenAI org verification.** gpt-image models may need a verified organization. That shows as a 403 "refused the request" error, which is not retryable.

## Behaviour notes
- Stopping a Grok video row doesn't cancel the job on xAI's side, because no cancel endpoint is documented. The banner says this.
- The Grok page shows both image and video fields at once. Only the fields for the chosen Output are used, because the framework's config panel has no conditional visibility.
- Video `count` = N separate jobs. Image `count` uses the API's `n` (≤10 per request) on both providers.
- xAI result URLs are temporary, and files are downloaded right away. Downloads never carry the API key.

## Next
- When the user adds keys: one OpenAI t2i row and one edit row with 2 refs, plus one Grok image row, one edit row and one 5 s 480p video row. Then check items 1–5 in the log.
- Phase 6 per `docs/02-phase-plan.md` (Characters library). Not started.
- Optional: conditional field visibility in `ConfigPanel` (hide video fields in image mode); a key-test button.
