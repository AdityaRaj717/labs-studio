# Phase 15 handoff: in-app help guide (done 2026-10-24)

## State
- Phase 15 of `docs/06-help-guide-plan.md` is built on branch `claude/phase-15-help-guide-e8f063`, which starts from phase 14b (`41ca31b`). Phase 14b had no newer commits to merge at the end. Not merged, not pushed.
- `pytest`: 384 passed (329 before). 55 are new, in `tests/test_help.py`. `test_config.py` and `test_flow_library.py` now expect the extra **Help** nav item.
- `python run.py` launches. The checks below ran the real `main()` offscreen, with app data in `D:\tmp_render\p15_launch`:
  - In Flow-only mode the sidebar shows Flow Image, Projects, Characters, Scenes, Webhook API, Detailed Log, Settings and **Help**.
  - Clicking the Characters page's "?" opened Help on *Characters and scenes*. Screenshot: `D:\tmp_render\p15_launch\help_page.png`.

## Content (`help/en/`)
- `README.md` is the table of contents. The app takes the topic order from its links, and on GitHub it's the folder's landing page.
- There are 13 topics:
  - getting-started: first launch, Flow-only mode and how to show everything, API keys, where files live
  - google-flow-sign-in: Web Sessions, step-by-step sign-in
  - flow-image
  - projects
  - characters-and-scenes
  - api-generators: Flow Video (Gemini), Grok, OpenAI
  - video-tools
  - video-editor
  - workflow
  - webhook-api: endpoints, body fields, curl for cmd.exe
  - mcp-agents
  - troubleshooting
  - terms-and-risks
- Each topic's title is its first `# ` heading. Links between topics are relative `.md` links, so the files read the same on GitHub.
- Each content point was checked against the handoffs and the code: config fields, button labels in `en.py`, webhook routes in `src/webhook/server.py`, and the Flow-only list in `src/features.py`. Hidden pages are described as hidden, with how to show them.
- **MCP client configs** were checked on 2026-10-24 against each client's docs:
  - [Claude Code](https://code.claude.com/docs/en/mcp): `claude mcp add <name> --scope user --env K=V -- node …`. The name goes before `--env`, and everything after `--` is the server command.
  - [Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers): Settings → Developer → Edit Config, `%APPDATA%\Claude\claude_desktop_config.json`, `mcpServers`, absolute paths, restart the app.
  - [Cursor](https://cursor.com/docs/context/mcp): `~/.cursor/mcp.json` or `.cursor/mcp.json`, `"type": "stdio"`, `command`, `args`, `env`.
  - [Codex](https://developers.openai.com/codex/mcp): `codex mcp add <name> --env K=V -- <cmd>` or `[mcp_servers.<name>]` in `~/.codex/config.toml`. `tool_timeout_sec` defaults to 60, so the guide sets 600 because a Flow image takes 1–2 minutes.

  The Claude Code page was too long to read whole. Only the parts about stdio servers, `--env`, `--scope`, `.mcp.json` and timeouts were read.
- The terms notice states that driving Flow or ChatGPT through the web is against their consumer terms and risks the user's own account. It links to Google's and OpenAI's terms and says the app has no ChatGPT web feature today.

## App (`src/help/`, `src/ui/help/`)
- `src/help/topics.py` (Qt-free) provides:
  - `help_dir()`: the source tree, or next to the exe / in `_MEIPASS` when frozen;
  - `load_topics(lang)`: falls back to `en` per file;
  - `search` (every word must match; title hits count double), `links`, `images` and `resolve_link`.
- `src/ui/help/page.py` `HelpPage`:
  - a search box, topic list and result count on the left; Back/Forward and a `QTextBrowser` (`setMarkdown`) on the right;
  - `.md` links open topics and `https` links open the browser;
  - images are scaled down to the view width on every resize;
  - search highlights the first hit.
- `src/ui/help/button.py` `attach_help_button(page, topic, on_click)` puts a 22 px round "?" in a page's top-right corner and keeps it there on resize.
- `MainWindow.PAGE_TOPICS` maps page keys to topics. `MainWindow.page()` attaches the button when it builds a page (not on placeholder pages), and `open_help(topic)` switches to Help. The pages' own code is unchanged.
- Sidebar: `("help", "nav_help", "\ue897")` after Settings, always shown. Settings' "?" opens *Signing in to Google Flow*, because Web Sessions is the only Settings tab in Flow-only mode.
- `en.py`: `nav_help` and `help_*` keys, appended at the end. `theme.py`: `#HelpButton` and `#HelpView` styles.

## Screenshots (`tools/make_help_screenshots.py`)
- One spec per image in `help/en/img/specs/<name>.json`. The format is in the `src/help/shots.py` docstring, and `validate_spec()` checks it.
- Targets are widget paths from the page, found again on every run, so moved widgets keep their callouts:
  - attributes, dict keys, `Class[i]`, `Class{attr=value}`;
  - `window:` to start from the main window;
  - a list for a bounding box.

  The shapes are `box` and `arrow`, with numbered badges.
- Run it from the repo root with one command:
  ```bat
  ..\..\..\.venv\Scripts\python.exe tools\make_help_screenshots.py
  ```
  From the main checkout the command is `.venv\Scripts\python.exe tools\make_help_screenshots.py`. Add spec names to redo only those.
- How it keeps real data out:
  - It runs offscreen. `QT_QPA_FONTDIR` points at `C:\Windows\Fonts`, because the offscreen platform has no fonts, and without it every letter is a box.
  - `APPDATA` points at a scratch folder (`D:\tmp_render\help_shots`, wiped each run). The QApplication is named `LabsStudioHelpShots`, so `config.app_data_dir()` never reaches the real one.
  - The demo data is projects Default / Episode 1 / Episode 2 with fake Flow URLs, the characters Mia and Captain Rook, the scene Bunker, six prompts in mixed states, and settings with `C:\Users\you\…` paths. There's no email or account data.
- 13 images, about 650 KB in total. `tests/test_help.py` checks:
  - every PNG has a valid spec, and every spec names a real page and setup step;
  - every image is used by a topic;
  - the numbered list under each image has one item per callout.

## Known gaps / notes
- **Flow Image at the default 1280 px window**: the fixed-width columns (674 px) leave the **Prompt** column about 60 px wide, so prompts wrap into a narrow strip. The screenshots use a 1600 px window. This is a UI fix for the prompt table, not done here.
- The Projects screenshot shows the scratch data path (`D:\tmp_render\help_shots\AppData\Roaming\LabsStudio\projects`), because the page prints the real data folder.
- The Web Sessions screenshot shows `C:\Users\you\AppData\Local\LabsStudio\…` for the profile and diagnose folders. These are not today's defaults (`D:\glabs_web\…`). They match what phase 13.1 plans.
- `QTextBrowser`'s Markdown has no heading anchors, so `topic.md#section` links open the topic at its top.
- Only English. A translation goes in `help/<code>/` with the same file names, and missing files fall back to English.
- Phase 13 must bundle `help/` (without `img/specs/`). That note is in `docs/04-projects-and-distribution-plan.md` → Phase 13. Rerun the screenshot tool before a release if the UI changed.
