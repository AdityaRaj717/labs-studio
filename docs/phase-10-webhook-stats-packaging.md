# Phase 10 — Webhook API, Stats tab, packaging (spec)

## Goal
- A **Webhook API** page: a local HTTP server that adds jobs to this app's generator pages and reports their status. It has start/stop, port and token controls.
- A **Stats** tab: jobs run, successes, failures and saved outputs per provider.
- A Windows build (PyInstaller) plus an Inno Setup installer script, with a build doc.

Done when an external `curl` submits a job that runs through the queue, the Stats tab shows counts, and the installer builds (or the handoff says what blocked it).

## Scope rules
- The server only drives this app's own `JobQueue`s, with the user's own keys and each page's current settings. It is not a proxy to any provider.
- It binds to `127.0.0.1` by default. "Allow other devices on my network" binds `0.0.0.0` and refuses to start without a token.

## Pieces
| Module | What it does |
|---|---|
| `src/webhook/server.py` | Qt-free. `WebhookServer(backend, host, port, token, on_request)` on a threaded `http.server` (`start/stop/running/url`; port 0 picks a free port). `parse_submit` validates request bodies. `ApiError(status, message)`. `new_token()`. |
| `src/ui/webhook/backend.py` | `PageBackend(page_lookup, stats)`: the server's backend. Page work (build page, add rows, start queue) is run on the GUI thread through a queued signal and waits up to 15 s (else 503). Job status is read straight from the `Job` objects. Remembers jobs submitted over the API. |
| `src/ui/webhook/page.py` | `WebhookPage(page_lookup, switch_page, store, stats)`: tab **API server** (status, port, token with Show/Generate, LAN checkbox, start-on-launch, Start/Stop, Open demo page, cmd.exe curl example with Copy, recent-requests log) and tab **Stats** (`StatsView`). `curl_example(url, token)`. |
| `src/stats/store.py` | Qt-free, thread-safe `StatsStore(path)`: `record`, `on_job_finished` (queue hook), `rows`, `totals`, `snapshot`, `reset`, `subscribe`. `default_stats()` = `<app data>/stats.json`. `install()` registers the hook. |
| `src/gen/queue.py` | New `add_finish_hook` / `remove_finish_hook`. Hooks get `(provider, job)` on the worker thread whenever a job ends as done, failed or stopped (not when a retryable failure is re-queued). |
| `packaging/` | `labs_studio.spec`, `version_info.txt`, `installer.iss`, `build.bat`. See `docs/phase-10-build.md`. |

Shared-file edits (additive): `src/app.py` (`demo` + `webhook` pages at the end of `register_pages`; `install_stats()` and webhook autostart in `main`), `src/languages/en.py` (`wh_*` keys at the end), `src/gen/queue.py` (the hook).

## HTTP API
All routes are under `/api`, JSON in and out. With a token set, every request needs `Authorization: Bearer <token>` or `X-Api-Token: <token>`; otherwise 401. The token is compared in constant time. Bodies over 1 MB get 413.

| Route | Result |
|---|---|
| `GET /api/health` | `{"ok", "app", "version", "token_required"}` |
| `GET /api/pages` | `{"pages": [{"key", "provider", "name", "running"}]}` for `flow_image`, `flow_video`, `grok`, `openai_image`, `demo` |
| `POST /api/jobs` | 202 `{"page", "started", "jobs": [job…]}` |
| `GET /api/jobs[?page=key]` | `{"jobs": [job…]}`: jobs submitted over the API this session |
| `GET /api/jobs/<id>` | one job, or 404 |
| `GET /api/stats` | `{"since", "providers": [{"key", "name", "jobs", "done", "failed", "stopped", "outputs"}], "totals"}` |

Submit body: `page` (required), `prompt` (string) or `prompts` (list, max 1000), optional `refs` (list of existing file paths, added to every row), `character` (a saved character's name, case-insensitive; attaches its reference images), `start` (default `true`).

Job object: `id, page, index, prompt, status (pending|queued|running|done|failed|stopped), progress (0–1), attempts, error, outputs (saved file paths), refs, character`.

Behaviour:
- Rows appear on the page like pasted prompts and use that page's current settings and output folder.
- `start: true` with the page idle calls the page's Start, which runs every pending row on that page (including rows added by hand). With the page already running, the new rows join the running batch.
- `demo` is a hidden page (not in the sidebar) on the offline `FakeProvider`, so the API can be tried with no key and no network. `[fail]` in a prompt makes that row fail.
- Errors: 400 bad body / unknown character / missing ref file, 404 unknown page or job, 405 wrong method, 503 the GUI didn't answer in 15 s.

## Settings
`webhook.port` (8765), `webhook.token` (""), `webhook.lan` (false), `webhook.autostart` (false), in `settings.json`. The token is a local shared secret, not a provider key, so it sits in `settings.json` rather than the Credential Manager.

## Stats
Every job that finishes on any `JobQueue` (generator pages, tool pages, API or UI) is counted per provider key. A retried job counts each time it finishes. Counts persist in `%APPDATA%\LabsStudio\stats.json`. The tab shows a Total row and success rate (done ÷ (done + failed)), and has a Reset button. The Workflow runner doesn't use `JobQueue`, so workflow runs are not counted.

## Tests (`tests/test_webhook.py`, 11)
Request parsing; server routes and token check against a dummy backend; busy port; end-to-end submit over HTTP to the fake-provider page on an ephemeral port (status, outputs, stats over the API and in the tab, `start: false`, unknown page); submit while running joins the batch; page token + refs + character; LAN needs a token; port-in-use message; stats store persistence/reset; queue hook counting (with a flaky retry); MainWindow registers `webhook` and `demo`.
