# Phase 4 — Flow Video on the Gemini API (spec)

Sidebar key `flow_video`. A `GeneratorPage` driven by `GeminiVideoProvider` (`src/gen/gemini_video.py`), using the user's own Gemini key (`get_key("gemini")`, the same key as Flow Image) and the official REST API only. Videos are saved unchanged as `.mp4`, so Google's SynthID watermark stays in them.

## Docs check (2026-10-20): Veo is going away
- The Gemini API Veo page (`ai.google.dev/gemini-api/docs/veo`) lists `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview` and `veo-3.1-lite-generate-preview` (Veo 3.0 is already deprecated). It says the 3.1 Preview models **shut down on October 22, 2026**, two days from now, and recommends migrating to **Gemini Omni Flash** (`gemini-omni-1.1-flash`). The Veo GA models live on the Gemini Enterprise Agent Platform (Vertex auth), which is out of scope for an API-key app.
- Veo used `models/{model}:predictLongRunning` → poll `GET {base}/{operation name}` → `response.generateVideoResponse.generatedSamples[0].video.uri` → download with the key header. **None of that is built**: the user has no key yet and won't have one before the shutdown, so it would be dead code the day it ships. Phase 3 dropped Imagen for the same reason.
- `gemini-omni-flash-preview` also shuts down on October 22, 2026. Only the stable `gemini-omni-1.1-flash` is offered.

## Endpoints (Interactions API, `v1beta`)
| Step | Call |
|---|---|
| Submit | `POST {base}/interactions`, header `x-goog-api-key` |
| Poll | `GET {base}/interactions/{id}` |
| Cancel | `POST {base}/interactions/{id}/cancel` (background interactions only) |
| Download (URI delivery only) | `GET <uri>` with the key header, redirects followed |

`base` = `https://generativelanguage.googleapis.com/v1beta`. The key always travels in the header, never in a URL.

### Request body
```json
{
  "model": "gemini-omni-1.1-flash",
  "input": "<prompt>"                      // or a list, see refs below
  "response_format": {"type": "video", "aspect_ratio": "16:9", "resolution": "720p"},
  "generation_config": {"video_config": {"task": "image_to_video"}},   // only when not "auto"
  "background": true,
  "store": true
}
```
- With refs, `input` is a list: `{"type": "image", "data": <b64>, "mime_type": "image/png"}` items, then `{"type": "text", "text": <prompt>}`. Images go through Phase 3's `encode_ref`, so big or odd files are shrunk to JPEG at 2048 px.
- The Omni page documents only synchronous calls (`background=false`). The general Interactions reference documents `background`, the statuses and `/cancel`. The provider asks for background so it can poll, report progress and cancel on Stop. **If the POST answer is already terminal (`completed` etc.), it's parsed straight away**, so a synchronous server reply works too. If the server rejects `background` with a 400 that names it, the provider resends once with `background: false, store: false` and waits on that single call, using the job timeout.

### Response
`status` is one of `queued | in_progress | requires_action | completed | failed | cancelled | incomplete`. The video sits in `steps[]`, inside a step with `type: "model_output"`, as a `content[]` item with `type: "video"`. That item has either `data` (base64) plus `mime_type`, or a `uri`. The provider also accepts a top-level `outputs[]` list of content items, in case the shape changes.

## Config fields (page-specific; the common ones come from Phase 2)
| key | kind | default | values |
|---|---|---|---|
| `model` | choice | `gemini-omni-1.1-flash` | that only, for now |
| `aspect` | choice | `16:9` | `16:9`, `9:16` |
| `resolution` | choice | `720p` | `360p`, `720p`, `1080p`, `4k` (1080p/4k are upscaled server-side) |
| `duration` | choice | `auto` | `auto`, `4`, `6`, `8`, `10` |
| `task` | choice | `auto` | `auto`, `text_to_video`, `image_to_video`, `reference_to_video` |
| `poll_interval` | int | 10 s | 2–60 |
| `timeout` | int | 600 s | 60–1800 (whole job: submit + poll) |

- **Duration:** Omni has no duration parameter, since length comes from the prompt (3–10 s output). Anything other than `auto` appends `" Make the clip about N seconds long."` to the prompt. `auto` sends the prompt unchanged.
- **Negative prompt:** Omni doesn't support one, so there's no field. Write negatives into the prompt ("No dialogue.").

## Refs → frames
The refs a row gets from Phase 2's ref matching (filename keyword or row number, sorted by name):
- `task` = `auto` / `image_to_video`: 0 refs → text-to-video. 1 ref → start frame. 2 refs → start + end frame (first by name = start, second = end). More than 2 → the first 2 are sent, with a warning in the log.
- `task` = `reference_to_video`: up to 3 refs are sent as subject references (the Omni page doesn't state a cap, so 3 matches Veo's limit). Extra refs are dropped with a warning.
- `generation_config.video_config.task` is sent only when the field isn't `auto`, because the docs say setting it adds constraints.

## Polling and progress
- Progress: 0.05 after the submit, then `0.05 + 0.85 * min(elapsed / expected, 1) ` while polling, where expected = 120 s (a guess; the real time depends on load). 0.95 while downloading, then 1.0.
- Poll every `poll_interval` s. The wait is sliced into ≤0.5 s steps, and `should_stop()` is checked at each one. On stop, `POST …/cancel` is sent (best effort, errors ignored), then `StopRequested`.
- After `timeout` s, the provider cancels and raises `ProviderError("timed out …", retryable=False)`. It's not retryable because a resubmit would bill again.
- `sleep` and `clock` are constructor arguments, so tests run with a fake clock and no real sleeping.

## Error mapping (reuses `gemini_image.map_http_error`)
| Case | Result |
|---|---|
| No key | `ProviderError("No Gemini API key. Add one in Settings → API keys.")`, before any request |
| Submit 401/403 / invalid key | not retryable |
| Submit 429, 5xx, network/timeout | retryable (the queue's auto-retry resubmits) |
| Poll 429/5xx/network | tolerated up to 3 times in a row (the job is already running and billed). After that, `ProviderError` not retryable |
| `status: failed` | `errors[0].message`. If it looks like a safety/policy block (safety, policy, blocked, prohibited, RAI, filtered), it says "Video refused by content policy (…)". Not retryable |
| `status: cancelled` (not by us) | not retryable |
| `completed`/`incomplete` with no video | "No video returned", plus any model text. Not retryable |
| Download non-200 | `map_http_error` |

## Output
`OutputFile(bytes, "mp4")` per video (`webm` if the mime type says so). `count` = N sequential interactions per row, like Flow Image. The prompt table's Output cell shows a drawn video placeholder for `.mp4/.webm/.mov`, not a frame. Grabbing a first frame needs QtMultimedia's async decoder, which isn't cheap. Double-click still opens the file.

## Banner
"Gemini Omni Flash video with your own key (Settings → API keys). Each clip costs credits on your Google account and carries Google's SynthID watermark. Veo 3.1 Preview shuts down on Oct 22, 2026, so it isn't offered."

## Tests (`tests/test_gemini_video.py`, all through `httpx.MockTransport`)
Request building (t2v, i2v start, start+end, reference, task/duration options). Poll loop (queued → in_progress → completed). Synchronous completed reply. Fallback when `background` is rejected. URI download. Stop during polling (with cancel). Timeout. Error mapping (auth, 429, 5xx, network, failed, safety-failed, no video, poll flakiness). No-key row. Thumbnail placeholder for `.mp4`. A page batch through the queue that saves `.mp4` files.
