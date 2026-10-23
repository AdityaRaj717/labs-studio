# Plan: consistent characters and scenes across videos (draft, 2026-10-23)

Goal (user): a channel (YouTube, Instagram…) reuses the same characters and places in many videos. The user gives character images to the agent, or adds them in the app. The app or agent then puts them in Google Flow's **Characters** and **Scenes** sections, and every video's images use them. Moodboard images should also live in those sections instead of being loose uploads.

## What Flow offers (seen 2026-10-23)
- Each project has its own **All media / Images / Characters / Scenes / Uploads** sections, plus **Library** (shared folders) and **Tools**.
- **New character** page: "Describe your character…" with a model picker (Nano Banana 2.1), a **Format** option, **Upload** and **Add from project**. Flow's own line: "Build and reuse characters for consistent videos."
- The prompt box's **+** opens an asset picker. It has a project switcher at the top-left (so assets from **other projects** can be picked), a search box, categories (All, Images, Videos, Voices, **Characters**, Avatars, Uploads) and **Add to prompt**. This is what the agent uses in place of drag and drop. A person can still drag images in by hand.
- Fixed now: references used to be uploaded again for every job (Uploads showed MD_01 five times). The MCP now searches the picker by file name and adds the existing asset, and uploads only when it isn't there yet (`addReference` in `generate-image.js`).

## Proposed design

### 1. One character library in the app (cross-project)
- The app already has a **Characters** page (phase 6: name and reference images). Add **Scenes** next to it with the same shape: name, description and images.
- Characters and scenes are global, not per project. A "series" or channel reuses them in every project.
- Each character or scene keeps a `flow` map: `{flow project URL → Flow character/scene name}`, so the app knows where it is already set up.
- Input paths:
  - drop images into the app's Characters or Scenes page;
  - give them to the agent ("this is Max, use him in every video"), which calls the app's webhook or the MCP;
  - describe one in text, and Flow generates the character sheet in its Characters section (this replaces our MD_xx moodboard images).

### 2. MCP tools (repo copy, `mcp/google-flow`)
| Tool | Does |
|---|---|
| `flow_list_characters {project_url}` / `flow_list_scenes` | Names (and thumbnails) in that project's section |
| `flow_create_character {project_url, name, prompt? , images?[]}` | Creates it on the New character page: upload, Add from project, or generate from the description; returns the name |
| `flow_create_scene {…}` | The same for Scenes |
| `flow_import_character {project_url, from_project_url, name}` | Brings a character over from another project through the picker's project switcher, with no new upload |
| `flow_generate_image … characters: [names], scenes: [names]` | Adds them as ingredients through the picker's Characters (and Scenes) category, so the agent references the real Flow character, not a loose image |

The old `flow_create_character`, `flow_import_character` and `flow_create_scene` tools in the MCP were written for the old Flow UI and need the same rework `generate-image.js` got.

### 3. App flow
- On project switch or first Flow job: for every character or scene used by the project's prompts, make sure it exists in that Flow project (create or import once, then reuse by name).
- Prompt rows keep their **Character** column (phase 6); add **Scene**. "Match characters" already finds them by name in the prompt.
- Webhook: `characters` and `scenes` lists per request.

### 4. Agent workflow (what the zombie test becomes)
1. `script.md` → `characters.md` (CH_01…) and `scenes.md` (SC_01…), in place of `moodboard.md`.
2. Create each one in Flow's Characters or Scenes section (from text, or from the user's images).
3. `images.md` lists the characters and scenes for each IMG instead of MD files, and generation adds them by name.
4. The next video in the same series imports the same characters into its new Flow project.

## To find out first (one exploration session, no credits)
- What a Flow character is after creation: a sheet, a single image, or an editable entity with a name? Does it show by name under the picker's Characters category, and does the agent treat it differently from a plain image?
- Whether Characters and Scenes are per project or shared through Library, and what "Format" offers.
- What the Scenes section's creation page looks like (it wasn't opened yet).
- Whether generating a character spends credits like an image does.

## Phasing
- **14a**: exploration above, plus MCP character and scene tools, plus `characters`/`scenes` on `flow_generate_image`.
- **14b**: app Scenes page, global library with the `flow` map, sync on switch and first job, webhook fields.
- **14c**: agent workflow docs and a rerun of the zombie test with characters and scenes, and a second episode reusing them.
