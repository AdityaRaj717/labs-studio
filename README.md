# Labs Studio

Desktop app (PySide6) for batch AI image and video generation. It talks to each
provider's official API with your own API key.

Status: phase 1, the app shell. Every page is a placeholder for now. See
`docs/02-phase-plan.md` for the roadmap.

## Setup (Windows, cmd.exe)

Needs Python 3.12 or newer. From the project folder:

```bat
python -m venv .venv
```

```bat
.venv\Scripts\activate
```

```bat
pip install -r requirements.txt
```

## Run

```bat
python run.py
```

## Test

```bat
pytest
```

## Build a Windows installer

See `docs/phase-10-build.md` (PyInstaller + Inno Setup, output on D:).

```bat
packaginguild.bat
```

## Webhook API

The **Webhook API** page runs a local HTTP server that adds jobs to the generator
pages. Routes and examples: `docs/phase-10-webhook-stats-packaging.md`.

## Where things are stored

`%APPDATA%\LabsStudio\`

- `settings.json`: theme, language, sidebar state, window geometry
- `logs\latest.log`: log of the current run (also shown on the Detailed Log page)
