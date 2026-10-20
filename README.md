# Labs Studio

Desktop app (PySide6) for batch AI image and video generation. It talks to each
provider's official API with your own API key: Google Gemini (images and video),
OpenAI Image and xAI Grok. It also has a characters library, video tools
(cutting, frame extraction, upscaling), a video editor, a workflow node editor
and a local Webhook API.

All ten phases in `docs/02-phase-plan.md` are built. Each phase has a spec and a
handoff note in `docs/` describing what it does and what's still unverified.

## Requirements

- Windows 10 or 11 (the app uses Windows fonts and Credential Manager; other
  systems are untested)
- Python 3.12 or newer, from [python.org](https://www.python.org/downloads/)
  (tick "Add python.exe to PATH" in the installer)
- Git
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

ffmpeg, if you want the video tools:

```bat
winget install -e --id Gyan.FFmpeg
```

## Run

With the venv active:

```bat
python run.py
```

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

Tests run offline: HTTP is mocked, subprocesses are faked, and the Webhook tests
only use 127.0.0.1.

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
| `src/gen/` | Job queue and providers (Gemini, OpenAI, Grok, offline demo), Qt-free |
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
- `characters\`: the characters library
- `stats.json`: the Stats tab counts

API keys are in Windows Credential Manager under `LabsStudio`.
