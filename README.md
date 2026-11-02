# Labs Studio

Desktop app (PySide6) for batch AI image and video generation. Its main path is
**Google Flow through your own signed-in browser**: the bundled google-flow MCP
server (`mcp/google-flow/`, Node.js) works Flow's web page in a Chrome window you
sign in to by hand, so generation runs on your Google AI subscription. It can
also use each provider's official API with your own key (Google Gemini, OpenAI
Image, xAI Grok). Around that: projects, a characters and scenes library, video
tools (cutting, frame extraction, upscaling), a video editor, a workflow node
editor, a local Webhook API and an in-app help guide.

Driving a consumer web app this way is against Google's terms for it and puts
your own account at risk; see `help/en/terms-and-risks.md`.

The plans are in `docs/02-phase-plan.md` to `docs/06-help-guide-plan.md`. Each
phase has a handoff note in `docs/` describing what it does and what's still
unverified.

## Requirements

- Windows 10 or 11 (the app uses Windows fonts and Credential Manager; other
  systems are untested)
- Python 3.12 or newer, from [python.org](https://www.python.org/downloads/)
  (tick "Add python.exe to PATH" in the installer)
- Git
- For Google Flow: [Google Chrome](https://www.google.com/chrome/),
  [Node.js](https://nodejs.org/) 18 or newer on PATH, and a Google account with
  access to Flow
- Optional: [ffmpeg](https://ffmpeg.org/) on PATH for Video Cut and the Video
  Editor, and `realesrgan-ncnn-vulkan.exe` for the Image Upscaler

## Install (cmd.exe)

Clone the repo (or your fork, with your username in place of `AdityaRaj717`):

```bat
git clone https://github.com/AdityaRaj717/labs-studio.git
```

```bat
cd labs-studio
```

Create a virtual environment and install the dependencies:

```bat
python -m venv .venv
```

```bat
.venv\Scripts\activate
```

```bat
pip install -r requirements.txt
```

Install the google-flow MCP server's packages (once, and again after it changes):

```bat
cd mcp\google-flow
```

```bat
npm ci
```

```bat
cd ..\..
```

ffmpeg, if you want the video tools:

```bat
winget install -e --id Gyan.FFmpeg
```

## Run

With the venv active:

```bat
python run.py
```

Next time, from a new cmd.exe window in the project folder, you can skip
activating the venv:

```bat
.venv\Scripts\python.exe run.py
```

### First run with Google Flow

1. Open **Settings → Web Sessions** and press **Launch browser**. A separate
   Chrome window opens with the app's own profile.
2. In that window go to `https://flow.google.com/` and sign in with your own
   Google account.
3. Back in the app press **Check login**; it should say **Signed in**.
4. On the **Flow Image** page paste or import prompts and press **Start**.

The **Help** page in the sidebar (and the **?** button on each page) walks
through every page with annotated screenshots. The same guide is in `help/en/`.

### Showing every page

By default the app starts in Flow-only mode and hides the pages that need API
keys. To show everything for one run:

```bat
set LABS_STUDIO_FEATURES=all
```

```bat
python run.py
```

Or set `"features": {"flow_only": false}` in `%APPDATA%\LabsStudio\settings.json`.
The **API demo** page and the Webhook API work with no key at all, through an
offline demo provider.

## API keys

Add keys in the app under **Settings → API keys**. They're stored in Windows
Credential Manager, never in the project folder. If no key is stored, the app
falls back to these environment variables:

| Provider | Variable |
|---|---|
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| xAI (Grok) | `XAI_API_KEY` |

## Test

```bat
python -m pytest
```

The Node engine suite is `cd mcp\google-flow && npm ci && npm test`. CI
(`.github/workflows/test.yml`) runs both offline suites on Windows.

Tests run offline: HTTP is mocked, subprocesses are faked, no browser is started,
and the Webhook tests only use 127.0.0.1.

## Help screenshots

After a UI change, regenerate every annotated screenshot in `help/en/img/`:

```bat
.venv\Scripts\python.exe tools\make_help_screenshots.py
```

Each image has a spec in `help/en/img/specs/` naming the widgets to point at.

## Use the Flow MCP from your own agent

`help/en/mcp-agents.md` has setup steps and config for Claude Code, Claude
Desktop, Cursor and Codex, the Production prompt-file format, and a recovery
guide. Agents must use the app's `FLOW_DATA_DIR` (default
`D:\glabs_web\flow-mcp`) so they share its single engine. See
`docs/adr/0001-flow-engine.md` and `GLOSSARY.md`.

## Webhook API

The **Webhook API** page runs a local HTTP server (127.0.0.1, port 8765 by
default, optional token) that adds jobs to the generator pages and reports their
status. Start it on that page, then for example:

```bat
curl -X POST http://127.0.0.1:8765/api/jobs -H "Content-Type: application/json" -d "{\"page\": \"demo\", \"prompt\": \"a red fox in the snow\"}"
```

All routes: `docs/phase-10-webhook-stats-packaging.md`. The **Stats** tab on
the same page counts jobs, successes, failures and outputs per provider.

## Build a Windows installer

PyInstaller plus Inno Setup. Details and the reasons for that choice are in
`docs/phase-10-build.md`. Build output goes to `D:\tmp_render\labs_build`; set
`LABS_BUILD_DIR` to put it somewhere else.

```bat
pip install "pyinstaller>=6.10"
```

```bat
winget install -e --id JRSoftware.InnoSetup
```

```bat
packaging\build.bat
```

## Project layout

| Folder | What's in it |
|---|---|
| `src/gen/` | Job queue and providers (Flow web, Gemini, OpenAI, Grok, offline demo), Qt-free |
| `src/web/` | Chrome session and the client for the google-flow MCP |
| `mcp/google-flow/` | The bundled google-flow MCP server (Node.js) |
| `src/projects/` | Projects |
| `src/help/`, `src/ui/help/`, `help/en/` | Help guide: loader, Help page, topics and screenshots |
| `tools/` | `make_help_screenshots.py` |
| `src/ui/` | PySide6 pages and widgets |
| `src/characters/`, `src/tools/`, `src/editor/`, `src/workflow/` | Characters, video tools, editor and workflow logic |
| `src/webhook/`, `src/stats/` | Local HTTP API and run statistics |
| `src/languages/en.py` | Every UI string |
| `tests/` | pytest suite |
| `docs/` | Findings, phase plan, a spec and handoff per phase |
| `packaging/` | PyInstaller spec, Inno Setup script, build script |

Each `docs/phase-*-handoff.md` explains how that part is wired and how to extend it.
For example, adding a provider is covered in `docs/phase-02-handoff.md`, and adding
a workflow node in `docs/phase-09-handoff.md`.

## Where things are stored

`%APPDATA%\LabsStudio\`

- `settings.json`: theme, language, page settings, window geometry, webhook settings
- `logs\latest.log`: log of the current run (also shown on the Detailed Log page)
- `outputs\<page>\`: generated files, unless a page has its own save folder
- `characters\`: the characters and scenes library
- `projects\`: projects (the folder can be changed on the Projects page)
- `stats.json`: the Stats tab counts

API keys are in Windows Credential Manager under `LabsStudio`.
