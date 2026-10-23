# Phase 12 handoff: projects + vendored google-flow MCP (done 2026-10-23)

## State
- Phase 12 of `docs/04-projects-and-distribution-plan.md` is built on branch `claude/phase-12-projects-93604c` (on top of phase 11a). Not merged, not pushed. Phase 13 (packaging) is deferred.
- `pytest`: 315 passed (303 before; new `tests/test_projects.py`). `python run.py` launches. The first launch migrated the real settings into a **Default** project.

## 12.0 MCP in the repo
- `mcp/google-flow/` is a copy of `D:\Tools\google-flow-browser-mcp`: src, package files, README, example config, `selectors.map.json`. It has no LICENSE file, but its README says MIT © TMSSS05, so `LICENSE` was written from that notice. Not copied: node_modules, chrome-profile, outputs, logs, screenshots, `config/flow.config.json` (holds the email) and `flow.projects.json`, all gitignored. **Make every MCP change here from now on**; `D:\Tools` is the old copy.
- Setup: run `npm ci --cache D:\tmp_render\npmcache` in `mcp/google-flow` (already done in this worktree, not in the main checkout).
- `src/utils/config.js` loads `FLOW_MCP_CONFIG`, else `config/flow.config.json`, else the example. It also reads the env overrides `FLOW_CDP_PORT`, `FLOW_CHROME_PATH`, `FLOW_CHROME_PROFILE_DIR`, `FLOW_DATA_DIR` and `FLOW_EXPECTED_ACCOUNT`. Logs, outputs, screenshots and the projects file go to the data dir. An empty `expectedAccount` accepts any account.
- New tool **`flow_open_project {url?, name?, create_if_missing=true}` → `{url, created, title}`** (`src/tools/open-project.js`):
  - It opens `url`, or creates a project through **New project** on `flow.google.com/`.
  - It sets the header title (`input[aria-label="Editable text"]`).
  - A project that is gone redirects to `/404?reason=project`, which is reported as `PROJECT_NOT_FOUND`.
  - `flow_generate_image` takes `project_url`, which wins over campaign.
- App: `web.flow_mcp_dir` defaults to `""`, meaning the repo copy (`BUNDLED_MCP_DIR`). A saved old `D:\Tools\…` value is also treated as the repo copy. The app passes the env (port, Chrome, profile, data dir `D:\glabs_web\flow-mcp`).

## 12.1 Project store (`src/projects/`)
- `<data root>/projects/<id>/project.json` holds: name, created/last_used, `output_dir` ("" = `<folder>/outputs`), `pages` (the same keys as the old `pages.*`), `rows` (per-page prompt rows with status and outputs) and `flow {url, title}`. The data root is `projects.data_root` ("" = app data). The active project is in `projects.active`.
- `projects.install()` sets `Settings.pages_backend`, so every `pages.*` get/set goes to the active project with no changes to the page code. Without `install()` (tests) nothing changes.
- `default_save_dir(page)` is now `<project output>/<page>`. The workflow page resolves its output folder when a run starts.
- Migration (first start, no projects): `pages.*` are copied into "Default", whose output folder is the old `%APPDATA%\LabsStudio\outputs`. Its Flow URL is taken over from the old MCP's `flow.projects.json` (campaign `labs-studio`). `settings.json` is not changed (its old `pages` block stays as a backup).
- Rows are saved 0.8 s after any change and on shutdown. Running or queued rows come back as stopped.

## 12.2 UI
- A project picker sits under the sidebar header, with a ⋯ menu: New, Rename, Duplicate settings, Open folder, Open in Flow, Delete. The **Projects** page (nav item) lists name, last used, output count, folder and Flow URL. It adds Output folder… and Change data folder… (restart needed).
- Delete asks first. "Delete, keep files" renames `project.json` to `project.deleted.json`, and only "Delete with files" removes the folder. The last project can't be deleted.
- Switching is refused while any queue or workflow runs (`MainWindow.is_busy`). A switch rebuilds the `PROJECT_PAGES` (generator and tool pages) from the new project. The window title shows the project.
- Webhook: `POST /api/jobs` takes `"project"` (name or id). It switches to that project first. An unknown project returns 404, and a project that can't be switched to because a batch runs returns 409. The response includes `"project"`.

## 12.3 Flow project per app project
- `FlowMcp.ensure_project(project)` opens or creates the Flow project and stores the URL and title in `project.json`. Every Flow job calls it, then passes `project_url`. On `PROJECT_NOT_FOUND` it makes a new project and retries once.
- When a project becomes active, or the active one is renamed, the app opens its Flow project in a background thread (`web.flow_open_on_switch`, default on). App startup does not open Flow; that happens before the first Flow job.

## Live checks (real account, 2026-10-23)
- Using a scratch store (`D:\tmp_render\p12\live`):
  - The Default project opened the old Flow project and retitled it "Default".
  - New project "P12 Alpha" created a new Flow project in 5 s, titled with its name.
  - Renaming it in the app renamed it in Flow, and the titles were still there after a reload.
  - A fake URL returned `PROJECT_NOT_FOUND`.
- One batch (user approved): x1, Nano Banana 2 Lite, 1K, 1:1, run in "P12 Alpha renamed" through the real `GeneratorPage` + `WebFlowImageProvider`. Done in 74 s, a 1024×1024 image in that project's `outputs\flow_image\…` folder, and the image appears in Flow project `af540247…`.
- Test project "P12 Alpha renamed" is still in the Flow account; delete it in Flow if you don't want it.

## Known gaps
- The switch and the two-project flows in the real window were checked through offscreen tests (`test_main_window_switch_rebuilds_project_pages`) and the launch screenshot, not by clicking.
- The output count walks the whole output folder, which can be slow for huge folders.
- Video, characters and other MCP tools still use the old campaign logic.
