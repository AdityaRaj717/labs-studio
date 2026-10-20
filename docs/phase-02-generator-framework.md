# Phase 2 — Generator framework

Build the shared "generator page" skeleton that every provider page (Flow Image, Flow Video, Grok, OpenAI, …) reuses. No provider network calls yet: a fake provider drives the whole pipeline so it can be run and tested offline. Read `docs/01-findings.md` ("The shared generator page pattern") and `docs/phase-01-handoff.md` first.

## Stack
- Same as phase 1 (Python 3.12+, PySide6). New deps: `openpyxl` (xlsx prompt import), `Pillow` (fake provider writes real PNGs; later phases reuse it for thumbnails and image prep).

## Package layout
```
src/
  gen/                    # Qt-free core, unit-tested without a GUI
    __init__.py
    models.py             # Job, JobStatus, OutputFile
    provider.py           # Provider base class, ProviderError, RunContext, ConfigField
    fake_provider.py      # FakeProvider: sleeps in steps, writes a PNG, fails on demand
    importer.py           # parse_text / load_txt / load_xlsx / load_prompts
    refmatch.py           # list_ref_images / match_refs
    output.py             # output_dir / save_outputs / slugify
    queue.py              # JobQueue: worker threads, delay, pause/resume/stop/retry, stats
  ui/generator/
    __init__.py
    config_panel.py       # ConfigPanel built from ConfigField lists, persisted per page
    prompt_model.py       # PromptTableModel (QAbstractTableModel over Job rows)
    prompt_table.py       # PromptTable view: progress delegate, empty hint, drag-drop, context menu
    stats_header.py       # StatsHeader: total / queued / running / done / failed / elapsed
    queue_bridge.py       # QueueBridge(QObject): JobQueue callbacks -> Qt signals (GUI thread)
    page.py               # GeneratorPage(page_key, provider): the assembled page
tests/
  conftest.py             # offscreen Qt + qapp fixture
  test_importer.py, test_refmatch.py, test_output.py, test_queue.py, test_generator_page.py
```

## Core (`src/gen`)
- **Job**: `id`, `index` (1-based row number), `prompt`, `refs: list[Path]`, `status`, `progress` (0–1), `outputs: list[Path]`, `error`, `attempts`. **JobStatus**: `pending, queued, running, done, failed, stopped`.
- **Provider** (base class): `key`, `name`, `config_fields() -> list[ConfigField]` (provider-specific fields such as model / aspect ratio), `generate(job, options, ctx) -> list[OutputFile]`. `OutputFile` = bytes + extension. `RunContext` gives `progress(p)` and `should_stop()`. Raise `ProviderError(msg, retryable=bool)` on failure.
- **FakeProvider**: configurable `step_seconds` and `steps`; reports progress per step, honours `should_stop()`, renders a PNG (solid colour from a hash of the prompt, prompt text drawn on it) `count` times. Any prompt containing `[fail]` fails (not retryable); `[flaky]` fails on the first attempt only (retryable). No network.
- **Import**: `parse_text(text, mode)` with mode `lines` (one prompt per non-empty line), `blocks` (blank-line separated, inner newlines kept as spaces) or `auto` (blocks if the text contains a blank line, else lines). `load_txt(path)` (utf-8, BOM tolerant), `load_xlsx(path)` (column with header `prompt` case-insensitive, else column A; empty cells skipped), `load_prompts(path)` dispatches on extension.
- **Ref auto-match**: images (`png jpg jpeg webp bmp gif`) in the ref folder. A file matches a prompt when its stem, normalised (lower case, `_`/`-` → space), appears as a whole-word phrase in the prompt, or when the stem is a plain number equal to the row index. A prompt can match several files; refs already attached by hand are kept.
- **Output**: base folder = page setting `save_dir`, default `<AppData>/LabsStudio/outputs/<page_key>`. `subdir_mode`: `none`, `date` (`YYYY-MM-DD`), `batch` (the batch start stamp `YYYYmmdd-HHMMSS`). File name `{index:03d}_{slug(prompt, 40)}_{n}.{ext}`; never overwrites (adds `-1`, `-2`, …).
- **JobQueue**: `start(jobs)` queues jobs and spawns `threads` worker threads; each worker waits a random `delay_min..delay_max` seconds before every job after its first. `pause()` stops new jobs being picked up (running ones finish), `resume()`, `stop()` marks queued jobs `stopped` and asks running jobs to stop. `retry(ids)` re-queues failed/stopped jobs and starts workers if idle. Retryable errors are retried up to `max_retries` times automatically. Callbacks `on_update(job)` and `on_finished()` fire from worker threads; `stats()` returns counts per status; `wait(timeout)` for tests. All shared state under one lock.

## UI (`src/ui/generator`)
- **ConfigPanel(page_key, fields, store)**: builds a form from `ConfigField(key, label_key, kind, default, options, minimum, maximum)` with kinds `choice`, `int`, `float`, `bool`, `folder`, `text`. Every change is saved to `pages.<page_key>.<key>` in the settings store (injected so tests use a temp file). Common fields every page gets: count per prompt, threads, delay min/max, save folder, subfolder mode, ref folder. Provider fields come first.
- **PromptTableModel**: columns `#`, Prompt (editable), Refs (count + names tooltip), Status (coloured text), Progress, Output (thumbnail of the first output). `refresh_job(id)` emits `dataChanged` for that row only.
- **PromptTable**: progress bar delegate, empty-state hint painted when there are no rows ("Paste prompts, import a .txt/.xlsx, or drop a file here"), drop `.txt/.xlsx` files to import, context menu: Edit…, Retry, Remove, Open output, Open folder. Double-click on Output opens the image with the OS viewer.
- **StatsHeader**: `Total · Queued · Running · Done · Failed · Elapsed`, updated from queue stats.
- **QueueBridge**: re-emits `JobQueue` callbacks as Qt signals so the table updates on the GUI thread.
- **GeneratorPage**: config panel on the left (scroll area), on the right a toolbar (Import file, Paste, Match refs, Clear | Start, Pause/Resume, Stop, Retry failed, Open output folder), the stats header and the table. Rows can't be edited/removed while running. The page logs batch start/finish via `logging`.

## Wiring
`app.py` registers `flow_image` with `MainWindow.register_page` as a `GeneratorPage` driven by `FakeProvider`, with a banner saying it is a demo provider. Phase 3 swaps in the real provider.

## Done when
- In the app, a batch of fake prompts runs through the queue with live row status, progress and thumbnails; pause/stop/retry work.
- `python run.py` launches; `.venv\Scripts\python -m pytest` passes (import, ref match, output naming, queue run/fail/retry/stop/pause, page end-to-end offscreen).
- `docs/phase-02-handoff.md` written; one commit on `main`.

## Out of scope
Real provider calls and API-key storage (phase 3+), character library, preview popup beyond opening the file with the OS. Same scope rules as phase 1: official APIs only, no multi-account automation, proxy rotation, bot-check workarounds or watermark stripping.
