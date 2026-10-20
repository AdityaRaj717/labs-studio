# Phase 6 spec: Characters library

Plan row: "Characters library (name, ref images, voice from Gemini TTS list) wired into the image/video pages. Done when a character can be attached to prompts."

## What a character is
- **Name** (unique, case-insensitive), **notes** (free text for the user, not sent anywhere), **voice** (one of Gemini's prebuilt TTS voices, or none), **reference images** (copies kept by the app).
- Stored under `<AppData>/LabsStudio/characters/`:
  - `characters.json`: `{"version": 1, "characters": [{"id", "name", "notes", "voice", "refs": [file names]}]}`, written atomically on every change.
  - `<id>/`: the copied reference images. Copies never overwrite: a clash becomes `name_2.png`.
  - `_previews/<Voice>.wav`: cached voice previews.
- Deleting a character removes its folder.

## Voices
- Static list of the 30 prebuilt voices with their style word (Zephyr/Bright … Sulafat/Warm), from the Gemini API speech-generation docs page, checked 2026-10-21. It's in `src/characters/voices.py` (`VOICES`).
- Optional **Preview** button: one call to `POST v1beta/interactions` with the user's Gemini key (`x-goog-api-key` header). The body is `{"model": "gemini-3.8-flash-lite-tts", "input": <text>, "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": <name>}]}}`. The reply's `audio` item is base64 WAV (headerless 16-bit PCM gets a 24 kHz mono RIFF header). The clip plays through QtMultimedia and is cached per voice, so each voice is billed once at most. No key → the status line shows "No Gemini API key…".
- The voice is stored with the character for later TTS/voice-over features. No generator provider uses it yet: Omni Flash video takes no voice parameter.

## Characters page (`characters` nav entry)
- Left: the character list (first ref as icon, tooltip with ref count and voice), **New character** and **Delete** (asks first).
- Right: Name, Voice combo + Preview, Notes, a reference image grid (Add images…, drag-and-drop image files, Remove selected), **Save**. Empty or duplicate names are refused with a message on the status line.

## Attaching to generator rows (Flow Image, Flow Video, Grok, OpenAI Image)
- Right-click rows → **Attach character ▸ <name>** (checked = current) and **Detach character**. This works on several selected rows.
- Toolbar **Match characters**: every row without a character whose prompt names one (whole-word, case-insensitive, longest name first) gets it.
- `Job.character` holds the id and `Job.character_refs` holds the paths it added. The character's images are put **first** in `job.refs`, so the providers send them as references with no provider changes. The row's own refs (ref-folder matches) stay after them.
- On **Start** each row with a character is re-synced from the library: images added or removed since attaching are picked up, and a deleted character is detached.
- The Refs column shows `@Name N` (N = total refs). The tooltip lists `@Name` and every file.
- Provider limits still apply: Gemini image up to 14 refs, Omni video up to 2 frames or 3 subject refs depending on task, OpenAI edits, Grok up to 5. On Flow Video, character images count as start/end frames in i2v mode. Use the `reference_to_video` task for character consistency.

## Out of scope
- Putting notes into the prompt, multiple characters per row, voice use in generation, character use in the Workflow editor's provider nodes.

## Tests (`tests/test_characters.py`, 15)
Store add/edit/delete/persist, ref copy/remove/name clash, corrupt index, listeners. attach/detach/sync/match-by-name. Character refs reach a Gemini image request body and an OpenAI edits multipart (MockTransport). Table signal attach/detach. Voice list, request shape, PCM→WAV, mocked preview. Characters page create/edit/dup-name/refs/preview-cache/delete. MainWindow registration.
