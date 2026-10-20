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

## Where things are stored

`%APPDATA%\LabsStudio\`

- `settings.json`: theme, language, sidebar state, window geometry
- `logs\latest.log`: log of the current run (also shown on the Detailed Log page)
