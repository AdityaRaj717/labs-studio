# Phase 5: OpenAI Image and Grok pages (spec)

Two `GeneratorPage`s on the Phase 2 framework, using the user's own keys and the official REST APIs only:

| Sidebar key | Provider | Key (Settings → API keys) |
|---|---|---|
| `openai_image` | `OpenAIImageProvider` (`src/gen/openai_image.py`) | `get_key("openai")`, env `OPENAI_API_KEY` |
| `grok` | `GrokProvider` (`src/gen/grok.py`) | `get_key("xai")`, env `XAI_API_KEY` |

Both keys are stored in Windows Credential Manager (service `LabsStudio`, user `openai` / `xai`) through the existing `KeyStore`. The key is sent only in `Authorization: Bearer …` to the API host. It never goes in a URL, log or error message, and never to the hosts that serve result files. Files are saved exactly as returned.

Shared helpers are in `src/gen/http_common.py`: `send`, `json_body`, `error_info`, `map_http_error(resp, who)`, `download`, `POLICY_RE`, `EXT_BY_MIME`. Reference images go through Phase 3's `encode_ref`, which shrinks anything over 4 MB, wider than 2048 px, or not PNG/JPEG/WebP to a 2048 px JPEG.

## Docs check (2026-10-20)
- **OpenAI** (developers.openai.com, image generation guide + CLI reference for `images edit`). Models: `gpt-image-2.5-flare` (fast, default), `gpt-image-2.5-sunburst` (edit precision), `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1-mini`. `chatgpt-image-latest` and dated snapshots exist but aren't offered. DALL·E isn't offered.
- **xAI** (docs.x.ai model capabilities + REST reference). Image models: `grok-imagine-image-2.0` (default, $0.04), `grok-imagine-image-quality` ($0.05), `grok-imagine-image` ($0.02). Video models: `grok-imagine-video-1.5` ($0.08/s, default), `grok-imagine-video-1.5-lite` ($0.02/s), `grok-imagine-video` ($0.05/s). `grok-imagine-image-pro` was deprecated in May 2026.

## OpenAI Image
| Row | Call |
|---|---|
| no refs | `POST https://api.openai.com/v1/images/generations`, JSON |
| refs | `POST https://api.openai.com/v1/images/edits`, multipart: repeated `image[]` files (up to 16) plus the same params as form fields |

Params: `model, prompt, n, size, quality, output_format`, plus `background` and `moderation` only when they aren't `auto`.
- `count` → the API's `n` (1–10 per request). Counts over 10 are split into several requests.
- Sizes: `auto`, `1024x1024`, `1536x1024`, `1024x1536` for every model. Custom sizes (`2048x2048`, `2048x1152`, `1152x2048`, `2560x1440`, `1440x2560`, `3840x2160`, `2160x3840`) only work on `gpt-image-2*`. On older models the row fails before any request is sent, with a non-retryable error.
- Quality: `auto/low/medium/high`, plus `xhigh/max` on `gpt-image-2.5-*`. On other models these drop to `high`, with a log warning.
- `background=transparent` with `jpeg` switches the format to PNG, with a log warning.
- Response: `data[].b64_json`. A `data[].url` is downloaded without the auth header. The file extension follows the response's `output_format`.

Error mapping (`map_http_error`):

| Condition | Message | Retryable |
|---|---|---|
| 401, or `invalid_api_key` | "rejected the API key" | no |
| `insufficient_quota` | quota/billing | no |
| 429 | rate limit | yes |
| 5xx | server error | yes |
| `moderation_blocked`, or policy words in the message | content policy | no |
| 403 (e.g. org not verified) | "refused the request" | no |
| other 4xx | the raw message | no |
| network error or timeout | | yes |

## Grok (xAI)
One page, with an **Output** field (`mode`): `image` or `video`.

**Image mode**
- No refs: `POST https://api.x.ai/v1/images/generations` (JSON).
- Refs: `POST /v1/images/edits` (JSON only, since xAI rejects multipart). One ref → `image: {url: data-URI}`. Two or more → `images: [{url}, …]`, capped at 5 (prompts can say `<IMAGE_0>` …).
- Body: `model, prompt, n, response_format: "b64_json", resolution (1k|2k)`, plus `aspect_ratio` unless `auto`, plus `quality (low|medium)` on `grok-imagine-image-2.0` unless `auto`.
- `count` → `n` (≤10 per request). The extension comes from `mime_type`, or else is sniffed (PNG magic, otherwise jpg).

**Video mode**
- `POST /v1/videos/generations` → `{request_id}`. Poll `GET /v1/videos/{request_id}` (200 or 202) every `poll_interval` s (default 5) until the status is no longer `pending`. Then download `video.url`, without the auth header, as `.mp4`.
- Body: `model, duration (1–15, default 8), resolution (480p|720p|1080p)`, `prompt` if not empty, `aspect_ratio` unless `auto`, and `generate_audio: false` only when the audio checkbox is off.
- Refs (`video_refs`): `auto` sends 1 ref as `image` (the start frame) and 2+ as `reference_images` (≤14). `start_frame` always uses the first ref. `references` always sends `reference_images`.
- Progress uses the API's `progress` (0–100) when present, and otherwise elapsed time / 90 s.
- `count` = N separate jobs, run one after another.
- Stop: polling stops and the row is marked stopped. **xAI documents no cancel endpoint**, so the job finishes and is billed on xAI's side. The banner says so.
- Job timeout (default 600 s) → non-retryable error. Poll hiccups (network/429/5xx) are tolerated 3 times in a row, then fail as non-retryable, because a resubmit would bill twice.
- Finished-poll parsing (`parse_video`):
  - `done` + `video.url` → OK.
  - `respect_moderation: false` or a policy-worded error → content policy, not retryable.
  - `expired` → not retryable.
  - `failed` → retryable only for `service_unavailable` / `internal_error`.

## Settings
`KEY_PROVIDERS` rows are now `(id, label_key, url, link_key)`:
- Gemini → AI Studio
- OpenAI → platform.openai.com/api-keys
- xAI → console.x.ai

## Tests
- `tests/test_openai_image.py` (17): request shapes, n splitting, multipart edits, option fix-ups, custom-size guard, URL delivery, error mapping.
- `tests/test_grok.py` (26): image and edit bodies, video submit/poll/download with a fake clock, ref modes, stop, timeout, poll flakiness, failure parsing.
- `tests/test_phase5_pages.py` (4): both pages through the real queue, the key rows, and the no-key row.

All HTTP goes through `httpx.MockTransport`.
