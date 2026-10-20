# Phase 2 handoff — Generator framework (done 2026-10-20)

## State
- Everything in `docs/phase-02-generator-framework.md` is built. `pytest`: 32 passed (11 from phase 1, 21 new).
- `python run.py` opens on **Flow Image**, which is now a real `GeneratorPage` running the offline `FakeProvider` (banner says so). No network calls anywhere.
- Offscreen screenshot of a 7-prompt batch: rows move Queued → Running → Done/Failed with coloured status, progress bars and output thumbnails; `[flaky]` row auto-retried and finished. Real-window check on Windows 11 done by eye in dark and light mode (fonts, layout, status colours, progress bars, thumbnails).
- New deps: `openpyxl`, `Pillow` (in `requirements.txt`, `pyproject.toml`, installed in `.venv`).

## Layout
- `src/gen/` is Qt-free: `models.py` (Job, JobStatus, OutputFile), `provider.py` (Provider, ConfigField, RunContext, ProviderError, StopRequested), `fake_provider.py`, `importer.py`, `refmatch.py`, `output.py`, `queue.py` (JobQueue, QueueSettings, count_statuses).
- `src/ui/generator/`: `config_panel.py` (ConfigPanel + COMMON_FIELDS), `prompt_model.py`, `prompt_table.py`, `stats_header.py`, `queue_bridge.py`, `page.py` (GeneratorPage).
- Wiring: `register_pages(window)` in `src/app.py` calls `MainWindow.register_page("flow_image", …)`. `MainWindow.closeEvent` calls `shutdown()` on any page that has one (stops workers).

## Hooks Phase 3+ builds on
- **New provider** = subclass `Provider`: set `key`/`name`, return its fields from `config_fields()` (model, aspect, …; shown above the common fields), implement `generate(job, options, ctx) -> list[OutputFile]`. Call `ctx.progress(p)` and check `ctx.should_stop()` (raise `StopRequested`). Raise `ProviderError(msg, retryable=True)` for rate limits / transient HTTP errors so the queue auto-retries (`max_retries` field). `options` holds every config value (provider + common: `count`, `threads`, …); `job.refs` holds matched reference images.
- **New page** = `window.register_page(key, lambda: GeneratorPage(key, MyProvider(), title=tr("nav_…")))` in `register_pages`. Replace the Flow Image line when its real provider lands.
- Settings live at `pages.<page_key>.<field>`; `ConfigPanel`/`GeneratorPage` take a `store` (any object with `get/set`) so tests use `Settings(tmp_path/...)`.
- Outputs: `<save_dir or AppData/LabsStudio/outputs/<page_key>>/<date|batch stamp|none>/{index:03d}_{slug}_{n}.{ext}`, never overwrites.
- Fake provider test hooks: `[fail]` in a prompt = permanent failure, `[flaky]` = one retryable failure.
- Tests: `tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen` and gives a `qapp` fixture; `run_until(qapp, cond)` in `test_generator_page.py` pumps events while the queue runs.

## Notes / known gaps
- Pause only holds new jobs; a running job finishes. Stop interrupts at the provider's next `should_stop()` check.
- Progress callbacks refresh one table row each; fine for a few threads, may want throttling if a provider reports very often.
- Failed rows keep the progress where they failed (intended, shows how far it got).
- No preview popup yet: double-click Output opens the file with the OS viewer.
- API-key storage / Settings page accounts section is not built (phase 3 needs it).

## Next
Phase 3 per `docs/02-phase-plan.md`: first real provider on top of this framework.
