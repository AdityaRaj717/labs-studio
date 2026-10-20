# Phase 1 — App shell

Build the skeleton the rest of the app hangs off. No generation logic yet; every page is a placeholder. Read `docs/01-findings.md` and `docs/02-phase-plan.md` first.

## Stack
- Python 3.12+, PySide6 (Qt 6 Widgets), packaged later with Nuitka.
- Deps: `PySide6`. Use a venv at `.venv`; put a `requirements.txt` and `pyproject.toml`.
- App data dir: `%APPDATA%\LabsStudio\` (use `QStandardPaths.AppDataLocation`). Big temp/cache under there too.

## Package layout
```
src/
  __init__.py
  app.py                 # entry: QApplication, splash, MainWindow
  config.py              # settings store (load/save JSON, defaults, dotted get/set)
  i18n.py                # translations dict + tr(key); en only this phase
  theme.py               # dark/light color tokens + qss builder
  languages/en.py        # nav_* and shell strings
  ui/
    main_window.py       # MainWindow: sidebar + QStackedWidget page router
    sidebar.py           # collapsible sidebar, SidebarButton, nav keys, theme toggle, version button
    splash.py            # splash screen shown during startup
    log_panel.py         # "Detailed Log" page: live log view fed by a logging handler
    pages/placeholder.py # PlaceholderPage(title) used for every not-yet-built page
run.py                   # python run.py launches the app
tests/
  test_config.py
```

## Behaviour
- **Sidebar** (collapsible, remembers collapsed state in settings). Nav items, in order, each routing to a `PlaceholderPage` for now:
  Flow Image, Flow Video, Grok Imagen, OpenAI Image, Meta Vibes, Meta Muse, Google Vids, Google Pics, Characters, Workflow, Video Editor, Image Upscaler, Video Cut, Webhook API, Course, Detailed Log, Settings.
  Labels come from `languages/en.py` `nav_*` keys (see findings table). Bottom of sidebar: theme toggle + a version button showing app version.
- **Page router**: `QStackedWidget`; `switch_page(key)` lazily builds a page the first time it's shown and caches it. Placeholder pages are cheap so build eagerly is fine this phase, but keep the lazy hook.
- **Theme**: `theme.py` exposes `COLORS[mode]` tokens (bg, panel, text, accent, border, hover, etc.) and `build_qss(mode)`. Toggling updates the whole app live and persists `settings["theme"]`.
- **Settings store** (`config.py`): JSON at app-data dir. `get(path, default)` / `set(path, value)` with dotted keys. Save on change (debounced or on close is fine). Keys this phase: `language`, `theme`, `sidebar_collapsed`, `window.geometry`.
- **i18n**: `tr("nav_img")` -> looks up current language dict, falls back to key. Only `en` now; structure so more languages drop in as `languages/<code>.py`.
- **Splash**: shown on launch, closed when MainWindow is ready.
- **Log panel**: a Python `logging.Handler` that appends to a QPlainTextEdit on the GUI thread (use a signal to marshal). App logs startup lines to it and to `%APPDATA%\LabsStudio\logs\latest.log`.

## Done when
- `python run.py` opens the window with a working sidebar; clicking any item shows its placeholder; theme toggle works and persists; settings survive a restart; window geometry restored.
- `pytest` passes (config get/set round-trip, theme token presence, every nav key resolves in en).
- A short `README.md` says how to set up the venv and run.

## Out of scope (later phases)
No provider calls, no queue, no real pages. Do NOT build any multi-account automation, proxy rotation, CAPTCHA/bot-detection handling, private-endpoint clients, or watermark removal — the clone uses official provider APIs only (see findings "What the clone will NOT reproduce").

## Naming
App display name "Labs Studio". Window title "Labs Studio". Don't reuse G-Labs branding, icons, or the original's bundled assets.
