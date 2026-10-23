# Plan: consistent characters and scenes across videos (draft, 2026-10-23)

Goal (user): a channel (YouTube, Instagram…) reuses the same characters and places in many videos. The user gives character images to the agent, or adds them in the app. The app or agent then puts them in Google Flow's **Characters** and **Scenes** sections, and every video's images use them. Moodboard images should also live in those sections instead of being loose uploads.

## What Flow offers (seen 2026-10-23)
- Each project has its own **All media / Images / Characters / Scenes / Uploads** sections, plus **Library** (shared folders) and **Tools**.
- **New character** page: "Describe your character…" with a model picker (Nano Banana 2.1), a **Format** option, **Upload** and **Add from project**. Flow's own line: "Build and reuse characters for consistent videos."
- The prompt box's **+** opens an asset picker. It has a project switcher at the top-left (so assets from **other projects** can be picked), a search box, categories (All, Images, Videos, Voices, **Characters**, Avatars, Uploads) and **Add to prompt**. This is what the agent uses in place of drag and drop. A person can still drag images in by hand.
- Fixed now: references used to be uploaded again for every job (Uploads showed MD_01 five times). The MCP now searches the picker by file name and adds the existing asset, and uploads only when it isn't there yet (`addReference` in `generate-image.js`).

## Findings from the live exploration (phase 14a, 2026-10-24)
- **A character is a named entity**, at `/project/<id>/character/<uuid>`. It has a name, a voice ("Select a voice"), **Character info** ("The Flow agent can use this information to help craft scenes with your character"), and a portrait. "Create body" adds a full-body image.
- **Cost**: on the New character page (`/character`), **Upload** or **Add from project** with one image creates the character straight from that image, with no generation and no credits. It takes about 10–30 s to process before the character page opens. Typing a description and pressing Start generation makes a portrait with the selected model (Nano Banana Pro / 2 Lite / 2.1). That is an image generation, which costs nothing on this account (the user says images are free; videos should use Omni Flash). The character page opens before the portrait is done, and leaving it early loses the portrait.
- **Format** (enabled once the description has text) rewrites a short description into a full studio-portrait prompt: medium shot, neutral expression, centred, plain white background. No image is made.
- **In the "+" picker** a character appears by name under the **Characters** tab, and the search box finds it. Clicking it adds it right away, with no "Add to prompt" needed, as an `Ingredient` chip with a character badge. The agent treats it as that character: an x1 Nano Banana 2.1 image with Survivor + Stranger + Bunker kept both faces, the clothes and the bunker.
- **Per project**: each project has its own Characters section. The card menu has Copy, but pasting into another project gives "Pasting characters across projects is not currently supported". The picker's **project switcher** can still add another project's character as an ingredient, without copying it. Library holds collections (folders) in the project and is not a shared character store.
- **Scenes are not places**: Add media → **New scene** at once creates an "Untitled Scene <date>" at `/scene/<uuid>`. That is a **video timeline editor** (clips, timeline, Omni 1.1 Flash prompt), and it has no Scenes tab in the picker. So a reusable *place* is kept as a **character**. Flow allows this ("The Wildcard: anything can be a character"), and a bunker image works as a character portrait. The MCP marks places by starting their Character info with `Place (a location, not a person): `.
- The character page's "Download image" saves only a 512 px preview. The portrait URL with `=s0` gives the original size, which the import uses.
- The agent chat can be collapsed down to just the prompt box. Its reply bubbles only render after **Expand**, so `flow_generate_image` now expands it first. Without that, the job timed out even though the image had been made.

## Built in 14a (MCP)
`flow_list_characters`, `flow_create_character`, `flow_import_character` (download the portrait at full size, then upload it with the same name and info), `flow_list_scenes` / `flow_create_scene` (places as characters), and `characters` / `scenes` on `flow_generate_image` (picker > Characters; `{name, project}` for another project). See `docs/phase-14a-handoff.md`.

## Built in 14b (app)
Scenes page, the global library with a `flow` map, sync on project switch and before each Flow job, Character and Scene columns, webhook `characters` / `scenes`, and the Flow-only switch that hides what doesn't work yet. See `docs/phase-14b-handoff.md`.

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

## To find out first
Answered in "Findings" above (14a).

## Phasing
- **14a**: exploration above, plus MCP character and scene tools, plus `characters`/`scenes` on `flow_generate_image`.
- **14b**: app Scenes page, global library with the `flow` map, sync on switch and first job, webhook fields.
- **14c**: agent workflow docs and a rerun of the zombie test with characters and scenes, and a second episode reusing them.
