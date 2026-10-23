# Phase 14b handoff: character and scene library, Flow sync, Flow-only app (done 2026-10-24)

## State
- Branch `claude/quirky-bhaskara-379d11`, fast-forwarded first to phase 14a (`1d32f14`, which sits on phase 12). Not merged, not pushed.
- `pytest`: 329 passed (315 before). New tests are in `tests/test_flow_library.py`. Small updates: `test_characters.py` (Character column), `test_config.py` (Scenes nav item) and `test_webhook.py` (new request keys).
- `python run.py` launches with only the working features visible. Screenshots: `D:\tmp_render\p14b\shots\` (Flow Image, Characters, Scenes, Settings, Webhook).

## Part A: library, sync, Scene column, webhook
**Library (`src/characters/store.py`).** Characters were already global (`%APPDATA%\LabsStudio\characters\`). Scenes use the same `CharacterStore` with `kind="scene"` under `scenes\scenes.json` (`scene_store()`). Every entry has a `flow` map, `{Flow project URL → name there}`, with `set_flow` / `drop_flow`. Saves are under a lock because the sync records names from worker threads. An old index without `flow` still loads.

**Rows (`src/gen/models.py`, `src/characters/attach.py`).**
- `Job.character` stays the first character. New fields:
  - `Job.cast`: more characters in the same shot, since Flow takes several.
  - `Job.scenes` and `Job.scene_refs`: the scene and the images it brought.
- `match_by_name` now attaches every character a row names (longest names win, so "Captain Mia" doesn't also count as "Mia") and its scenes. Rows that already have a character keep it.
- Rows round-trip through `project.json` (`cast`, `scenes`, `scene_refs`).

**Prompt table.** New **Character** and **Scene** columns. The old `@name` in Refs is gone, and Refs is now a count. The right-click menu has:
- Attach character (replaces), and **Add character to the shot**
- Detach character
- **Set scene** and **Clear scene**

**Match characters** also matches scenes.

**Sync (`src/characters/flow_sync.py`, `FlowSync`).** `ensure(kind, id, project_url)` returns the entry's Flow name in that project:
1. If it is already recorded for that project, it uses that name.
2. If it is recorded in another project, `flow_import_character` copies it from there. When the import fails, for example because the source project is gone, it falls back to step 3.
3. Otherwise `flow_create_character` / `flow_create_scene` creates it from `images[0]`, which is free. An entry with no images but with notes is created from the notes with `auto_confirm`, so Flow generates a portrait (an image generation). An entry with neither raises `SyncError`.

The notes go to Flow as the Character info. `verify(url)` runs `flow_list_characters` once per project per session and drops recorded names that were deleted in Flow, so they get set up again.

**When it runs.**
- When a project becomes active: `open_project_async` opens its Flow project, then `FlowMcp.sync_project` sets up every character and scene that the project's saved rows (all pages) use. Errors are logged and don't stop anything.
- Before every Flow job: `FlowMcp.generate_image(args, timeout, characters=[ids], scenes=[ids])` calls `sync.names()`, which verifies once per session and sets up anything missing. It then passes the `characters` / `scenes` **Flow names** to `flow_generate_image`.
- `WebFlowImageProvider` sends the row's character and scene ids and leaves their images out of `reference_images`, because Flow already has them as characters. The row's own refs are still uploaded.
- Without app projects, characters can't be synced. That raises `INVALID_PARAMS`, which stops the queue.

**Characters / Scenes pages (`src/ui/characters/page.py`).**
- The Scenes page is `CharactersPage(kind="scene")`: name, description, images, and no voice.
- Both pages have an **In Google Flow** row that shows whether the entry is in this project's Flow project or in N others. The tooltip lists the URLs.
- The **Set up in this project's Flow** button runs `ensure` in a thread.

**Webhook.** `POST /api/jobs` takes `characters: [names]` and `scenes: [names]`, matched case-insensitively against the library. The old `character` is still accepted and goes first. An unknown name returns 400 and lists the known names. The job info returned now includes `characters` and `scenes` (ids).

## Part B: Flow-only mode (`src/features.py`)
One switch: setting `features.flow_only` (default `true`), or the environment variable `LABS_STUDIO_FEATURES=all|flow`, which wins over the setting (tests run with `all`). Setting it to `false` brings everything back. Nothing was deleted.

| Hidden | Why |
|---|---|
| Flow Video page | Gemini API video (Veo/Omni) needs an API key. Flow web video isn't wired into the app yet (the MCP has `flow_generate_video`; use Omni Flash and ask first) |
| Grok Imagen, OpenAI Image pages | API-key providers, not the Flow path |
| Meta Vibes, Meta Muse, Google Vids, Google Pics, Course | Placeholder pages with nothing behind them |
| Workflow | The node editor runs Gemini API and demo nodes. It has no Flow node |
| Video Editor, Image Upscaler, Video Cut | Local ffmpeg / Real-ESRGAN tools, not part of the Flow path |
| Gemini API provider on Flow Image | Needs an API key. The page now runs only "Google Flow web (image)", with no provider picker |
| Settings → API keys tab, Tools tab | Only the hidden providers and tools use them. Web Sessions stays |
| Character voice + Preview | Gemini TTS needs an API key |
| Webhook "Open demo page" button, the `demo` page | Offline fake provider for testing. The webhook only accepts `flow_image` |

What stays: Flow Image (web), Projects, Characters, Scenes, Webhook API (`flow_image` only), Detailed Log, Settings (Web Sessions). Checked in `test_app_in_flow_only_mode_shows_only_working_features` and in the launch screenshots.

## Live check (real account, 2026-10-24)
Script: `D:	mp_render\p14b\live14b.py`. It uses a scratch app data folder (`D:	mp_render\p14b\liveppdata`) and the existing test project "P12 Alpha renamed" (`af540247-5670-4fb4-969e-ffa12a51a6ed`). Log: `D:	mp_render\p14b\liveun.log`.
- Library:
  - **Survivor**, recorded in Zombie Bunker, with the portrait from the 14a import.
  - **Stranger**, recorded in Zombie Bunker, with no local image.
  - The new scene **Shelter**, made from the bunker image, with a description.
- One prompt row: "Survivor and the Stranger share a can of beans by candlelight in the Shelter…". **Match characters** filled Character "Survivor, Stranger" and Scene "Shelter".
- **Sync** (the project-switch path, `open_project_async`), 47 s in total:
  - Survivor imported (P12 already had a Survivor, so the MCP reused it).
  - Stranger imported from Zombie Bunker.
  - Shelter created in P12 as a place, from the image.
  - All three recorded in the `flow` maps.
- **Generation** through the real `GeneratorPage` + `WebFlowImageProvider` (x1, default model, 1K): done in 69 s. Flow's agent replied "featuring Survivor and the Stranger … inside the Shelter".
  - Output: `D:	mp_render\p14b\liveppdata\LabsStudio\outputslow_image6-10-24_survivor-and-the-stranger-share-a-can-of_1.jpg`, 1024×1024.
  - Both faces, the clothes (red scarf, olive parka) and the bunker match the characters.
- Leftovers in Flow: "P12 Alpha renamed" now also has **Stranger** and **Shelter**, plus this image.
- No video was generated.

## Known gaps / next
- Characters and scenes share Flow's Characters section, so a scene with the same name as a character would collide there. The app doesn't stop that yet.
- `verify` trusts names. A character renamed in Flow by hand is seen as gone and set up again.
- An entry's images or notes changing later doesn't update its Flow copy. Delete it in Flow, or clear its `flow` entry, to set it up again.
- The row menu has no "remove one character from the shot". Detach clears them all.
- 14c: agent workflow docs and the zombie rerun with characters and scenes (`docs/05-characters-and-scenes-plan.md` → Phasing).
