# Phase 3 handoff — Flow Image on the Gemini API (done 2026-10-20)

## State
- Everything in `docs/phase-03-gemini-image.md` is built. `pytest`: 61 passed (32 before, 29 new). All HTTP in tests goes through `httpx.MockTransport`. No live API call has been made with the user's key.
- `python run.py` opens on **Flow Image**, now driven by `GeminiImageProvider` (banner says it uses the user's key and that images carry SynthID). With no key, every job fails before any request, and the row shows "No Gemini API key. Add one in Settings → API keys." in red in the Output cell (tooltip too).
- **Settings** is a real page now: a tab widget with an **API keys** tab (Gemini row: masked entry, Show, Save, Remove, a source status line, a link to AI Studio).
- Real-window screenshots (Windows 11, dark): `D:\tmp_render\phase3\phase3_flow_image.png`, `phase3_settings_keys.png`.
- New deps: `httpx`, `keyring` (in `requirements.txt`, `pyproject.toml`, installed in `.venv`).

## Deviation from the plan row
The row said "Gemini/Imagen". The current Gemini API docs say Imagen is shut down, so the page targets the native Gemini image models through `models/{model}:generateContent`. The model list is in `MODELS` in `src/gen/gemini_image.py` (`gemini-3.1-flash-image` default, `gemini-nano-banana-2.1`, `gemini-3-pro-image`, `gemini-3.1-flash-lite-image`, `gemini-2.5-flash-image`). These IDs come from the docs page and haven't been checked live, so verify them on the first real run.

## Layout
- `src/keys.py`: `KeyStore(backend, environ)` with `get/set/clear/source/env_var` per provider id, plus the module-level `store()` / `get_key(provider)`. The keyring service is `LabsStudio` and the username is the provider id. The env fallback map `ENV_VARS` already lists `openai` and `xai`.
- `src/gen/gemini_image.py`: `GeminiImageProvider(key_source, transport, api_base)`, `build_request`, plus module helpers `encode_ref`, `map_http_error`, `parse_response`.
- `src/ui/pages/settings_page.py`: `SettingsPage(keys)` → `ApiKeysTab` → `KeyRow` per entry in `KEY_PROVIDERS`.
- `src/ui/generator/prompt_model.py`: failed rows show `job.error` in the Output cell.
- `src/app.py` `register_pages`: `flow_image` → Gemini, `settings` → `SettingsPage`. `FakeProvider` stays for tests only.

## Hooks for later phases
- **New provider with a key**: add `(id, label_key, url)` to `KEY_PROVIDERS` and env vars to `ENV_VARS`, then take a `key_source` callable plus an optional `transport` in the provider (copy the Gemini pattern). Read the key inside `generate()` so a newly saved key works without a restart.
- **Error mapping pattern**: auth (401/403/invalid key) → not retryable; 429 and 5xx and network/timeout → `retryable=True`; content-policy refusals and "no image" → not retryable, with the reason in the message. Never put the key in a URL, message or log.
- Settings tabs: add more with `SettingsPage.tabs.addTab(...)`.
- Phase 4 (Veo) uses the same Gemini key (`get_key("gemini")`) and the same `map_http_error`.

## Notes / known gaps
- `count` runs N sequential calls per job (the image models return one image per call).
- No key-test button: it would hit the network, so it was left out until the user wants it.
- Refs: up to 14, shrunk to JPEG at 2048 px if the file is over 4 MB, larger than 2048 px, or not PNG/JPEG/WebP.
- Under a named QApplication, `config.app_data_dir()` uses Qt's AppDataLocation, so setting `APPDATA` doesn't move it. Screenshot scripts write to the real `%APPDATA%\LabsStudio\settings.json`. This session restored the delay values it changed. A future fix: an env override such as `LABS_STUDIO_DATA` in `app_data_dir`.
- The Interactions API (beta) also generates images. It isn't used here.

## Next
Phase 4 per `docs/02-phase-plan.md`: Flow Video (Veo) on the same key and error mapping.
