# Phase 14a handoff: Flow characters and scenes in the MCP (done 2026-10-24)

## State
- Built on branch `claude/inspiring-volhard-06bce6`, fast-forwarded first to phase 12 (`b8ace81`). Not merged, not pushed.
- `pytest`: 315 passed (no Python changes in this phase).
- What Flow's Characters and Scenes actually are is written up in `docs/05-characters-and-scenes-plan.md` → "Findings". In short: a character is a named entity with info and a portrait. Making one from an image is free. Characters are per project. Flow's **Scenes are video timelines**, so a reusable place is kept as a character marked as a place.

## MCP tools (`mcp/google-flow/src/tools/`)
| Tool | File | Notes |
|---|---|---|
| `flow_list_characters {project_url, details?}` | `create-character.js` | Names from the Characters section (waits for the filter, then for the list to settle). `details` opens each one for kind/info/url. |
| `flow_create_character {project_url, name, images?, prompt?, info?, format?, auto_confirm?, from_project_title?}` | `create-character.js` | `images[0]` is a local file (Upload) or a project image name (Add from project, by search). Prompt-only runs only with `auto_confirm` and waits for the portrait. A name that already exists is reused. |
| `flow_import_character {project_url, from_project_url, name}` | `import-character.js` | Fetches the portrait at full size (`=s0`) into `<data dir>/characters/` and creates it again in the target with the same name and info. Flow refuses cross-project paste. |
| `flow_list_scenes`, `flow_create_scene` | `create-scene.js` | Places: characters whose info starts with `Place (a location, not a person): `. |
| `flow_generate_image … characters, scenes` | `generate-image.js` | Each entry is `"Name"` or `{name, project}`. Added through picker > Characters; the picker's project switcher is always set, because it remembers the last project. The prompt is wrapped in `CHAR_TEMPLATE`, which names them. |
- `open-characters.js` and the `flow_open_characters` tool were removed (they targeted the old labs.google UI).
- Fix in `generate-image.js`: the agent chat can be collapsed, and its bubbles only render after **Expand**. The job now presses Expand before the new-session step and again while it waits. Before this fix a successful generation timed out.

## Live checks (real account, Zombie Bunker project `b8d61203…`)
- Characters created free from project images: **Survivor** (MD_02), **Stranger** (MD_03, by the tool), and the place **Bunker** (MD_01).
- `flow_import_character` copied Survivor and Bunker into "P12 Alpha renamed" (`af540247…`). Bunker arrived at full size, 1376×768, with its place info. The first Survivor import ran before the full-size fix and got the 382×512 preview; re-import it if that project matters.
- Cross-project picker entry `{name: "Stranger", project: "Zombie Bunker…"}` reached the prompt in P12 Alpha. This was prepare-only, and the prompt was cleared afterwards.
- Prompt-only character **Infected** (Format on, Nano Banana 2.1): the first try lost its portrait because the tool left the page early. That empty character is in the project's Trash. After the fix the portrait appeared.
- Images: `D:\tmp_render\p14\out\P14A_chars_test.jpg` (Survivor + Stranger + Bunker, beans) and `P14A_chars_test2.jpg` (+ Infected at the vent, full tool path). Faces, clothes and bunker stay consistent. In the second image the agent swapped who does what, so the prompt alone doesn't fix who does which action.
- One run got "The server encountered a temporary connection issue", reported as `GENERATION_REFUSED`. The retry passed.
- Leftovers in Flow: an empty "Untitled Scene 10-23 18:25:51" and the first "Infected" are in Zombie Bunker's Trash. P12 Alpha now has Survivor and Bunker.

## Known gaps / next (14b, 14c)
- `flow_list_scenes` opens every character to read its info, about 3 s each.
- Only the first image makes a character. More views would need "Create body" or edits, which are generations.
- A transient server error isn't retried automatically.
- The app side (Scenes page, global library with a `flow` map, sync on switch, webhook `characters`/`scenes`) is 14b. Passing `characters`/`scenes` through `src/web/flow_mcp.py` is part of 14b too.
- Videos: the user says to use Omni Flash.
