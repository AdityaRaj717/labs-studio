# Build plan: projects + a shareable, self-contained app

Goal (user, 2026-10-23):
1. **Projects.** Keep several named projects in Labs Studio, pick one and generate in it. Picking a project also opens its own project in Google Flow, and creates the Flow project if it doesn't exist yet.
2. **Works anywhere.** The packaged app can be sent to a friend. They install it, sign in to Google Flow once when the app asks, and generate. No Node, no MCP folder, no D: drive, no settings to type in. It should feel like any big desktop app.

State before this plan: phase 11a (`docs/phase-11a-handoff.md`, branch `claude/phase-11a-flow-images-a698ec`). Flow images go through the google-flow MCP, which lives outside the repo at `D:\Tools\google-flow-browser-mcp` and has machine-specific defaults (D: paths, a fixed Chrome path, port 9333). The generator pages have no project concept. "Project" exists only in the video editor.

Ground rules from `docs/03-web-automation-plan.md` still apply: the user signs in by hand, nothing types or stores passwords, no CAPTCHA workarounds, one account per site, one job at a time, a daily cap. Each friend uses their own Google account.

## Phase 12: projects (+ the MCP moves into the repo)

**12.0 Vendor the MCP.** Copy `D:\Tools\google-flow-browser-mcp` (src, package.json, package-lock.json, README, LICENSE if any, `config/flow.config.example.json`, `selectors.map.json`) into the repo as `mcp/google-flow/`. Leave out node_modules, chrome-profile, outputs, logs, screenshots, the real `flow.config.json` (it has the user's email) and `flow.projects.json`. Keep its license notice (the README says MIT; check). From then on every MCP change happens in the repo copy. `web.flow_mcp_dir` defaults to the repo copy when running from source. Running `npm ci` there creates node_modules, and the README says how.

**12.1 Project store.** Each project is `<data root>/projects/<id>/project.json` holding:
- name and created/last-used dates;
- an output folder (default `<data root>/projects/<id>/outputs`, changeable);
- per-page settings, the same keys as today's `pages.<page>.*`;
- per-page prompt rows: prompt, refs, character, status and outputs, so lists survive a restart and a switch;
- the Flow project: URL and title.

The data root is a setting, defaulting to the app data folder. Today's settings and outputs become the **Default** project on first start (migration, no data loss).

**12.2 UI.**
- An always-visible project picker (sidebar header or a top bar) with New, Rename, Delete (asks first, never deletes output files unless asked), Duplicate settings and Open folder.
- A Projects page listing projects with their last-used date and output count.
- Switching is refused while any page has a batch running. The webhook takes an optional `"project"` and defaults to the active one.

**12.3 Flow project per app project.**
- When a project becomes active (and before its first Flow job), the app opens that project's Flow project in the shared Chrome tab.
- If the project has no Flow project yet, or the stored one is gone, a new Flow project is created and titled with the app project's name (Flow's editable project title).
- This needs an MCP tool `flow_open_project {name, key, create_if_missing}` → `{url, created}`. Generation then targets that URL (pass a `project_url` or `campaign = key` to `flow_generate_image`).
- Detect "project gone": the page redirects home or shows no agent prompt box.

Done when the app launches; two projects can be created, switched, renamed and deleted; each keeps its own prompts, settings and output folder after a restart; picking a project opens its Flow project, and a new project gets a new Flow project with its name (one small real check, with the user's OK); a Flow batch lands in the active project's Flow project and output folder; the webhook honours `project`; `pytest` passes; `docs/phase-12-handoff.md`.

## Phase 13: shareable install (depends on 12) — DEFERRED

**Deferred (user, 2026-10-23):** don't bundle or package yet; the user has more features to add and test first. Build this phase last, after the remaining feature phases.

**13.1 No machine-specific defaults.** Every default path comes from the app data / local app data folders, for example the Chrome profile in `%LOCALAPPDATA%\LabsStudio\browser-profile` and diagnostics and temp files under `%LOCALAPPDATA%\LabsStudio`. The user's own settings keep their D: paths. Find Chrome automatically (registry App Paths, Program Files, `%LOCALAPPDATA%\Google\Chrome`) and fall back to Microsoft Edge (also Chromium, CDP works). If neither is found, show a clear message with a download link. Choose a free CDP port automatically if 9333 is taken by something that isn't ours.

**13.2 MCP as part of the app.**
- Bundle a pinned Node.js runtime (portable `node.exe`, license notice included) and `mcp/google-flow` with its production `node_modules` into the PyInstaller output, then the installer.
- The app starts the MCP from the bundle; a user setting can override it.
- The MCP takes its config and data locations from environment variables or arguments the app passes (port, profile dir, projects file, outputs, logs, screenshots), all under the user's writable app data. Nothing is written into the install folder (Program Files is read-only).
- The MCP must not need `expectedAccount`: no hard-coded email; whoever signs in is the account.

**13.3 First-run and sign-in flow.** On the first Flow use, or from a "Connect Google Flow" button on the image page and in Web Sessions:
1. explain in one screen what happens (your own Google account, the app opens a browser window, you sign in yourself);
2. open the browser with the app's profile on Flow;
3. watch for sign-in (account button visible) and show progress;
4. once signed in, say so and let generation start. The signed-in state persists across restarts.

If Flow shows the sign-in wall later, the app shows the same flow instead of only an error. Other states get plain-language messages: no subscription, Flow not available in the region (Flow shows its own page), a CAPTCHA (solve it yourself in the window).

**13.4 Package and installer.**
- Update `packaging/labs_studio.spec` and `build.bat` for the selectors, the Node runtime and the MCP.
- Use Inno Setup per-user install (already `PrivilegesRequired=lowest`), with a Start menu entry and an uninstaller that keeps user data unless asked.
- Version shown in the app.
- **Ship the help guide (phase 15).** Bundle `help/` (the Markdown topics and the screenshots in `help/<lang>/img/`; the `img/specs/` JSON is not needed) so the Help page works in the installed app. `src/help/topics.py` `help_dir()` looks for it next to the executable. Rerun `tools/make_help_screenshots.py` before building if the UI changed.
- Test on a clean Windows user account or VM if available, otherwise a fresh local Windows user, with no Python, Node or D: drive assumptions. Sign in there with a test Google account the user provides by hand.

Done when the installer builds; a clean Windows user with only Chrome or Edge can install, sign in through the app and generate Flow images in a project, without editing any setting; uninstall works; `pytest` passes; `docs/phase-13-handoff.md` lists anything the friend still has to do (for example, Windows SmartScreen on an unsigned exe).

## Order

12 → 13, one session each, because both touch `src/web/flow_mcp.py`, `src/config.py` and the vendored MCP. Each session stays under ~300k context, starts from the phase 11a branch (or main, once 11a is merged), and commits on its own branch without merging or pushing.
