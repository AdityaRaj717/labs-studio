# Phase 3 — Flow Image on the Gemini API + Settings → API keys

Replace the Flow Image demo provider with the first real backend: Google's **Gemini API** native image models ("Nano Banana"), called with the user's own API key. Add a Settings page with an **API keys** tab where that key is entered. Read `docs/phase-02-handoff.md` (Provider, ConfigField, RunContext, ProviderError, `register_pages`) first.

## Why Gemini and not Imagen
The plan row says "Gemini/Imagen". As of 2026-10 the Gemini API docs state the Imagen models are shut down and point to the native Gemini image models through `generateContent`. So this phase targets those only. Imagen's `:predict` endpoint is not implemented.

## Stack
- New deps: `httpx` (HTTP client; tests use `httpx.MockTransport`, so no network in pytest) and `keyring` (Windows Credential Manager for the key).

## Package layout
```
src/
  keys.py                    # KeyStore: get/set/clear/source per provider (keyring + env fallback)
  gen/gemini_image.py        # GeminiImageProvider: request building, response parsing, error mapping
  ui/pages/settings_page.py  # SettingsPage (QTabWidget) with the API keys tab
tests/
  test_keys.py, test_gemini_image.py, test_settings_page.py
```

## Official API used
- Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- Auth: header `x-goog-api-key: <key>` (never in the URL, so it can't leak into logs).
- Request:
  ```json
  {
    "contents": [{"role": "user", "parts": [
      {"inlineData": {"mimeType": "image/png", "data": "<base64 ref>"}},
      {"text": "<prompt>"}
    ]}],
    "generationConfig": {
      "responseModalities": ["IMAGE"],
      "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"}
    }
  }
  ```
  `imageSize` is sent only for models that support it (not `gemini-2.5-flash-image`; Flash Lite is 1K only).
- Response: `candidates[].content.parts[].inlineData {mimeType, data}` → one `OutputFile` per image part (extension from the MIME type). Parts flagged `"thought": true` are skipped. Text parts are ignored.
- The newer beta **Interactions API** (`/v1beta/interactions`) also does images; it is not used here because `generateContent` is the stable core endpoint. Switching later only touches `gemini_image.py`.
- Images carry Google's SynthID watermark. The clone saves the bytes unchanged.

## Config fields (provider fields, above the common ones)
| key | kind | default | options |
|---|---|---|---|
| `model` | choice | `gemini-3.1-flash-image` | `gemini-3.1-flash-image`, `gemini-nano-banana-2.1`, `gemini-3-pro-image`, `gemini-3.1-flash-lite-image`, `gemini-2.5-flash-image` |
| `aspect` | choice | `1:1` | `1:1 3:2 2:3 3:4 4:3 4:5 5:4 9:16 16:9 21:9` |
| `image_size` | choice | `1K` | `1K 2K 4K` |
| `timeout` | int | 120 | seconds, 10–600 |

`count` (outputs per prompt, a common field) = that many sequential `generateContent` calls per job; progress = finished calls / count, `should_stop()` checked before each call.

## References
`job.refs` (hand-attached or auto-matched from the ref folder) are sent as `inlineData` parts before the prompt text, up to 14 (extra refs are dropped with a log warning). Files over 4 MB, or larger than 2048 px on a side, are re-encoded to JPEG at 2048 px max with Pillow to stay under the request size limit; others are sent as-is with their MIME type.

## API key storage and entry
- `KeyStore` (`src/keys.py`), one entry per provider id (`gemini` now; `openai`, `xai` later):
  - stored in the OS keyring (`keyring`, service `LabsStudio`, username = provider id), which on Windows is Credential Manager, so the key is never written to `settings.json`;
  - fallback when nothing is stored: environment variable (`GEMINI_API_KEY`, then `GOOGLE_API_KEY`);
  - `source(provider)` → `keyring` | `env` | `none`, for the UI;
  - keyring backend errors are logged and treated as "no key" (the env fallback still works).
- The provider gets a `key_source` callable so tests inject a key without touching the real keyring.
- **Settings page** (`settings` nav item) → **API keys** tab: one row per provider (Gemini for now): masked line edit, Show toggle, Save, Clear, a status line ("Saved in Windows Credential Manager", "Using the GEMINI_API_KEY environment variable", "Not set") and a link to Google AI Studio's key page. No "test key" network call in this phase.

## Errors → `ProviderError(retryable=…)`
| Condition | Message | retryable |
|---|---|---|
| no key | "No Gemini API key. Add one in Settings → API keys." (checked before any request) | no |
| 400 with `API_KEY_INVALID`, 401, 403 | "Gemini rejected the API key (…)" | no |
| 429 `RESOURCE_EXHAUSTED` | "Rate limit or quota reached (…)" | yes |
| 500, 502, 503, 504 | "Gemini server error <code> (…)" | yes |
| timeout / connection error | "Network error: …" | yes |
| other 4xx (bad model, bad argument, region) | "Gemini error <code>: <message>" | no |
| `promptFeedback.blockReason` set | "Prompt blocked by Gemini safety filters (<reason>)" | no |
| `finishReason` in `SAFETY`, `IMAGE_SAFETY`, `PROHIBITED_CONTENT`, `IMAGE_PROHIBITED_CONTENT`, `BLOCKLIST`, `SPII`, `RECITATION` | "Image refused by content policy (<reason>)" | no |
| no image part (`NO_IMAGE` or text only) | "No image returned (<reason>): <first text part>" | no |

Retryable errors go through the queue's existing `max_retries`. The key never appears in a message or log line.

## Wiring
- `register_pages` replaces the Flow Image demo line with `GeneratorPage("flow_image", GeminiImageProvider(), banner=tr("gemini_banner"))` and registers `settings` → `SettingsPage`.
- `FakeProvider` stays for tests.

## Done when
- Flow Image builds with `GeminiImageProvider`; jobs go through the queue (status, progress, outputs saved). With no key set, each job fails with the clear "No Gemini API key" error in its row.
- Settings → API keys saves/clears the key (keyring) and shows where it comes from.
- `.venv\Scripts\python -m pytest` passes with mocked HTTP (request building, response parsing, error mapping incl. auth / rate limit / server / content policy, key handling). `python run.py` launches.
- `docs/phase-03-handoff.md` written; one commit on `main`. No live API call unless the user asks.

## Out of scope
Interactions API, multi-turn editing, Google Search grounding, upscale, other Settings tabs (tools, stats, logs), a key-test request. Same scope rules: official API, user's own key, one account, no proxy rotation, no bot-check workarounds, watermarks kept.
