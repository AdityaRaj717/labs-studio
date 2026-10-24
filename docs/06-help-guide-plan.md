# Plan: in-app help guide (phase 15, 2026-10-24)

Goal (user): Labs Studio will be published, so a stranger who just installed it needs a guide inside the app. It should explain every page, getting signed in to Google Flow, and connecting the bundled google-flow MCP to the user's own agent. The same text should be publishable on GitHub later, and its screenshots should be easy to refresh after UI changes.

State before this plan: phase 14b (`docs/phase-14b-handoff.md`, branch `claude/quirky-bhaskara-379d11`). The app runs in **Flow-only mode** by default (`src/features.py`): Flow Image (web), Projects, Characters, Scenes, Webhook API, Detailed Log and Settings (Web Sessions) are shown. Everything else is hidden until `features.flow_only` is set to `false` or `LABS_STUDIO_FEATURES=all`. The help has to say what is hidden and how to show it, and must not describe features that don't exist.

## 15.1 Content: Markdown in `help/en/`
- One file per topic. `help/en/README.md` is the table of contents: an ordered list of links to the topic files. The app reads its order from it, and on GitHub it is the landing page of the folder.
- A topic's title is its first `# ` heading. Its id is the file stem (`flow-image.md` → `flow-image`).
- Links between topics are relative `.md` links (`[Projects](projects.md)`), so they work on GitHub and in the app. External links are `https://…`.
- Images are `img/<name>.png`, made by the screenshot script (15.3). Numbered callouts in an image match a numbered list under it.
- Other languages later go into `help/<code>/` with the same file names. The app falls back to `en` for missing files.

Topics:

| File | Covers |
|---|---|
| `getting-started.md` | First launch, what's shown in Flow-only mode and how to show everything, API keys (Settings → API keys, Credential Manager, env vars) |
| `google-flow-sign-in.md` | Chrome + profile, Settings → Web Sessions (Launch browser, Check login, Diagnose page, daily cap, gaps), Node.js and the MCP folder |
| `flow-image.md` | The Flow Image page: config panel, Paste / Import / Match refs / Match characters, the prompt table and its menu, Start / Pause / Stop / Retry failed, outputs |
| `api-generators.md` | Flow Video (Gemini API), Grok Imagen and OpenAI Image (hidden by default; need keys) |
| `projects.md` | Phase 12: the picker, the Projects page, per-project prompts, settings, output folder and Flow project |
| `characters-and-scenes.md` | Phase 6 / 14a / 14b: the library, Character and Scene columns, Match characters, how they get into Flow (free from an image) |
| `video-tools.md` | Image Upscaler and Video Cut (ffmpeg, Real-ESRGAN, Settings → Tools) |
| `video-editor.md` | Timeline, auto-edit, subtitles, export |
| `workflow.md` | Node editor: nodes, ports, Run |
| `webhook-api.md` | Endpoints, token, LAN mode, curl examples for cmd.exe, `project` / `characters` / `scenes`, Stats tab |
| `mcp-agents.md` | Using `mcp/google-flow/` from your own agent: install, one Chrome, config for Claude Code, Claude Desktop, Cursor and Codex (checked against each client's docs), tool list |
| `troubleshooting.md` | Error messages and what to do, Detailed Log, Diagnose snapshots, where files live |
| `terms-and-risks.md` | Plain notice: driving Flow (or ChatGPT) through the web is against those services' consumer terms and puts your own account at risk |

## 15.2 Help page in the app (`src/ui/help/`, `src/help/`)
- `src/help/topics.py` (Qt-free): `load_topics(lang)` → ordered `Topic(id, title, path, text)`; `search(topics, query)` → topics whose title or text contains every word, ranked by hits; `links(topic)` and `images(topic)` for the tests; `help_dir()` finds `help/` next to the source tree or in a PyInstaller bundle.
- `src/ui/help/page.py`: `HelpPage` with a search box and topic list on the left and a `QTextBrowser` on the right (`setMarkdown`, search path = the topic's folder). Clicking a `.md` link opens that topic, `https://` opens the browser, and Back/Forward follow topic history. Wide images are scaled to the view width. Search highlights the first hit.
- Sidebar: a **Help** nav item after Settings, always shown.
- "?" buttons: `src/ui/help/button.py` `attach_help_button(page, topic)` puts a small round "?" in the page's top-right corner. `MainWindow.page()` adds it to each page from a `PAGE_TOPICS` map, so page code doesn't change. Clicking it switches to Help on that topic.
- All UI strings through `tr()` (`help_*` keys appended to `en.py`).

## 15.3 Screenshots that regenerate (`tools/make_help_screenshots.py`)
- Runs offscreen with a scratch app data folder (`APPDATA` pointed at a temp dir on D:, the QApplication *not* named LabsStudio, so `config.app_data_dir()` stays out of the real one). It builds a real `MainWindow` with a demo project store, demo prompt rows, demo characters and scenes, and settings with no account data and no email.
- One JSON spec per screenshot in `help/en/img/specs/<name>.json`: page key, feature mode (`flow` or `all`), window size, optional setup step (a named function in the script, for demo rows), optional crop, and callouts. A callout targets a widget by attribute path from the page (`"widget": "start_btn"`, `"stats_header"`) or by object name, or a fixed `rect`. Each callout is a tight box round the target plus a numbered label pill with an arrow to it (changed after review: the first version had badges on loose boxes). Targets are found again on every run, so moved widgets keep their callouts.
- `validate_spec()` checks the spec shape. The script fails loudly if a target widget isn't found.
- Output: `help/en/img/<name>.png`. Running it again refreshes every image.

## 15.4 Tests (`tests/test_help.py`)
Topics load in README order with titles; every README entry exists and every topic is in the README; search finds and ranks; every relative link resolves to a topic file; every image exists; every spec validates and has a PNG; every `PAGE_TOPICS` topic exists; the Help page opens a topic and follows a link; the "?" button opens its topic.

## 15.5 Packaging note
Phase 13 must ship `help/` (Markdown and `img/`, not `img/specs/`) in the PyInstaller bundle; `help_dir()` already looks next to the executable. Noted in `docs/04-projects-and-distribution-plan.md` → Phase 13.

Done when the app launches, the Help page shows every topic with annotated screenshots, the "?" buttons open the right topic, `pytest` passes, and `docs/phase-15-handoff.md` is written. One session, under ~300k context, on branch `claude/phase-15-help-guide-e8f063` from phase 14b. Merge any newer 14b commits before finishing and regenerate the screenshots.
