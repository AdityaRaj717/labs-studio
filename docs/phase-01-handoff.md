# Phase 1 handoff — App shell (done 2026-10-20)

## State
- All Phase 1 spec items in `docs/phase-01-app-shell.md` are built. `pytest`: 11 passed.
- Headless check (offscreen Qt): all 17 sidebar pages open, theme toggles dark → light and is saved, window geometry is saved on close, `latest.log` is written by `python run.py`.
- Venv at `.venv` (Python 3.13, PySide6 6.12, pytest 9). Git repo started on `main`.
- Code indexes: graft (`graft build`, cache in `graft/`) and codebase-memory-mcp (project `D-Programming-Self-Learning-Projects-Misc-GLabs-Clone`). Use them to navigate instead of reading whole files.

## Hooks Phase 2 builds on
- `MainWindow.register_page(key, factory)` and `switch_page(key)` in `src/ui/main_window.py`: pages are built lazily on first view. Replace a placeholder by registering a real factory for its key.
- `NAV_ITEMS` in `src/ui/sidebar.py`: `(key, label_key, glyph)` tuples, 17 items, order tested.
- Settings: `src/config.py` `get/set` with dotted keys (`pages.<key>.<field>` is the intended namespace for per-page config). `app_data_dir()` gives `%APPDATA%\LabsStudio`.
- Theme: `src/theme.py` `COLORS[mode]`, `build_qss(mode)`, `apply_theme(app, mode)`, `current_mode()`.
- i18n: `src/i18n.py` `tr(key, **fmt)`; add strings to `src/languages/en.py`.
- Logging: `setup_logging` in `src/ui/log_panel.py`; use `logging.getLogger(__name__)` and the log page picks it up.

## Notes
- No manual look at the real window yet (only offscreen); worth a quick `python run.py` check by eye.
- Real app-data dir comes from `QStandardPaths`, so setting `APPDATA` does not redirect it once `QApplication` is up. Tests use `Settings(tmp_path / ...)` directly.

## Phase 2 — Generator framework (next)
From `docs/02-phase-plan.md`: reusable config panel, prompt table model/view, prompt import (txt/xlsx/paste), ref-folder auto-match, queue manager (threads, delay, pause/stop/retry), output saving, stats header. Ship a fake provider for tests.
Done when: a fake job batch runs through the queue with live row status, app launches, `pytest` passes.
First step: write `docs/phase-02-generator-framework.md` (spec like phase 1's), then build. New deps: `openpyxl` (xlsx import), `Pillow` if thumbnails are needed.
