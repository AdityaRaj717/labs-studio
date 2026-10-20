# Phase 6 handoff: Characters library (done 2026-10-21)

## State
- Everything in `docs/phase-06-characters.md` is built. `pytest`: 249 passed (234 before, 15 new). No network in tests. No live TTS call has been made.
- `python run.py` launches. The **Characters** sidebar entry is a real page. Every generator page has a **Match characters** button and Attach/Detach character in the row context menu.
- Real-window screenshots (Windows 11, dark, temp settings and a temp store, no network): `D:\tmp_render\phase6\phase6_characters.png`, `phase6_flow_image_rows.png`. The real `%APPDATA%\LabsStudio` was not touched by the script.
- No new deps (QtMultimedia ships with PySide6).

## Layout
- `src/characters/store.py`: `Character`, `CharacterStore(root)` (`all/get/by_name/ref_paths/add/update/delete/add_refs/remove_ref/subscribe`), `default_store()` (app-data singleton, created lazily).
- `src/characters/attach.py`: `attach/detach/sync/match_by_name/character_label`. Qt-free.
- `src/characters/voices.py`: `VOICES`, `voice_label`, `build_preview_request`, `parse_audio`, `as_wav`, `preview_voice(voice, text, key_source, transport)`.
- `src/ui/characters/page.py`: `CharactersPage(store=None, key_source=None, transport=None)`.

## Shared-file edits
- `src/app.py`: 2 lines at the end of `register_pages` (`characters` → `CharactersPage`).
- `src/languages/en.py`: `char_*` and `gen_*character*` keys appended at the end.
- `src/gen/models.py`: `Job.character`, `Job.character_refs` (new fields with defaults).
- `src/ui/generator/page.py`: `characters=` kwarg, `characters` property, `set_character`, `match_characters`, `_sync_characters` (called at the top of `start`), Match characters button.
- `src/ui/generator/prompt_model.py`: `character_name` hook, used by the Refs column text and tooltip.
- `src/ui/generator/prompt_table.py`: `character_requested(list, str)` signal, `characters_source` hook, `_character_menu`. Refs column 50 → 90 px.
- No provider was changed: character images arrive through `job.refs`.

## Unverified until a real run
1. TTS model id `gemini-3.8-flash-lite-tts` and the Interactions reply shape for audio (`outputs[]` / `steps[].content[]` item `{"type": "audio", "data", "mime_type"}`). The parser also accepts headerless PCM.
2. The voice list is static. If Google adds voices, extend `VOICES`.

## Notes
- The Workflow editor (Phase 9) builds its own `Job`s, so characters aren't wired there. A "Character" node that emits refs would be a small add in `src/workflow/nodes/`.
- Phase 10's webhook API can attach characters by name through `CharacterStore.by_name` + `attach.attach`.

## Next
Phase 10 per `docs/02-phase-plan.md`.
