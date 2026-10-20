# Phase 10 handoff: Webhook API, Stats tab, packaging (done 2026-10-21)

## State
- Everything in `docs/phase-10-webhook-stats-packaging.md` is built, on branch `claude/gifted-bassi-f514f9`. Not merged, not pushed.
- `pytest`: 260 passed (249 before, 11 new in `tests/test_webhook.py`). Tests use only 127.0.0.1 on ports the OS picks. No external network.
- `python run.py` launches. The **Webhook API** sidebar entry is a real page with two tabs, **API server** and **Stats**. `main()` was also checked with settings redirected to `D:\tmp_render\phase10\main_check`: with `webhook.autostart` on, the server came up, answered `/api/health`, and stopped when the window closed.
- **PyInstaller build works:** `D:\tmp_render\labs_build\dist\LabsStudio\LabsStudio.exe` (163 MB folder, about 3 min clean build). The frozen exe started and logged "Main window ready". Every module that's loaded by name (languages, workflow nodes, keyring's Windows backend, webhook, stats) is in the bundle (checked in PyInstaller's xref report).
- **Installer not built.** Inno Setup 6 isn't installed on this PC, and I didn't install system software without asking. `packaging\installer.iss` is written but has never been compiled. To finish, run these two commands in cmd.exe from the repo root:
  ```bat
  winget install -e --id JRSoftware.InnoSetup
  ```
  ```bat
  packaging\build.bat
  ```
  The installer lands in `D:\tmp_render\labs_build\installer\LabsStudio-Setup-0.1.0.exe`.
- New dev dependency: `pyinstaller` (installed in `.venv`, listed as the `build` extra in `pyproject.toml`, not in `requirements.txt`). Pip's cache for it went to `D:\tmp_render\labs_build\pipcache`.

## Verified with a real curl (cmd.exe)
Real window, webhook on port 8799 with token `demo-token-123`, settings and app data under `D:\tmp_render\phase10` (script: `D:\tmp_render\phase10\smoke.py`).

Submit three jobs to the offline demo page:
```bat
curl -X POST http://127.0.0.1:8799/api/jobs -H "Content-Type: application/json" -H "Authorization: Bearer demo-token-123" -d "{\"page\":\"demo\",\"prompts\":[\"a red fox in the snow\",\"a lighthouse at dusk\",\"an [fail] owl\"]}"
```
The reply was 202 with job ids 1–3 (`started: true`). Then:
```bat
curl http://127.0.0.1:8799/api/jobs/1 -H "Authorization: Bearer demo-token-123"
```
returned `"status": "done"` with the saved PNG path. Job 3 came back `failed` with "Fake failure requested by prompt", as the `[fail]` tag asks. The same POST without the header got HTTP 401. `GET /api/stats` and the Stats tab both showed Demo provider: 3 jobs, 2 succeeded, 1 failed, 2 outputs, 67%.

With the default settings (port 8765, no token), the command shown on the page is:
```bat
curl -X POST http://127.0.0.1:8765/api/jobs -H "Content-Type: application/json" -d "{\"page\": \"demo\", \"prompt\": \"a red fox in the snow\"}"
```

Screenshots: `D:\tmp_render\phase10\phase10_webhook.png`, `phase10_stats.png`, `phase10_demo.png`.

## Something to know
The first frozen-exe launch used the real `%APPDATA%\LabsStudio`, because QStandardPaths ignores an overridden `APPDATA` variable. Someone closed that window, so the usual close-time save (geometry, last page) went to the real `settings.json`. Nothing else was written. The webhook was not enabled there.

## Layout and shared-file edits
- New: `src/webhook/server.py`, `src/stats/store.py`, `src/ui/webhook/{backend,page}.py`, `packaging/*`, `tests/test_webhook.py`, these docs.
- `src/gen/queue.py`: `add_finish_hook` / `remove_finish_hook`, plus a call at the end of `JobQueue._run` for jobs that ended as done, failed or stopped.
- `src/app.py`: the `demo` and `webhook` pages at the end of `register_pages`. `main()` installs the stats hook and starts the webhook if `webhook.autostart` is set. The hook is installed in `main()`, not `register_pages`, so tests that call `register_pages` never write to the real `stats.json`.
- `src/languages/en.py`: `wh_*` keys appended at the end.
- `README.md`: short Build and Webhook sections.

## Known gaps
- The API can't change page settings per request (model, aspect, count). Jobs use whatever the page is set to.
- `start: true` on an idle page runs every pending row there, including rows the user added by hand and hasn't started.
- The API remembers job ids only for the current session. Restarting the app forgets them, although the files stay on disk.
- No HTTPS. LAN mode sends the token in clear over the local network. It's off by default and refuses to start without a token.
- Workflow runs aren't counted in Stats, because the runner doesn't use `JobQueue`.
- The exe has no icon and isn't code-signed, so SmartScreen will warn. See `docs/phase-10-build.md`.
- Installer untested (see above).

## Next
This was the last phase in `docs/02-phase-plan.md`. What's left: compile and try the installer once Inno Setup is installed, then the live-key checks listed in the phase 3–6 handoffs.
