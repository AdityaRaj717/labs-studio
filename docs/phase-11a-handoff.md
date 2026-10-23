# Phase 11a handoff: browser core + Google Flow images via the google-flow MCP (done 2026-10-23)

## State
- Phase 11a of `docs/03-web-automation-plan.md` is built on branch `claude/phase-11a-flow-images-a698ec`. Not merged, not pushed.
- **Image generation goes through the google-flow MCP server** (`D:\Tools\google-flow-browser-mcp`). The user asked for this after the first version, which drove Flow from Python directly. The app starts the MCP as a child process and calls its `flow_generate_image` tool once per job. The Python Flow adapter from the first version was removed.
- `pytest`: 303 passed (260 before phase 11). No browser and no Node in pytest: the provider uses a fake MCP backend, the stdio client runs against a small fake MCP server (`tests/fixtures/fake_mcp_server.py`), and block detection is checked on saved HTML snapshots.
- `python run.py` launches. The image page has a **Provider** picker: "Gemini API (image)" (as before) or "Google Flow web (image)". Settings has a new **Web Sessions** tab.
- New dependency: `playwright>=1.49` in `requirements.txt` and `pyproject.toml`, installed in `.venv` with the pip cache on `D:\tmp_render\pipcache`. The app's own Playwright use is now only for Web Sessions (Check login, Diagnose, bring-to-front). Generation needs Node.js and the MCP folder. It was also installed by mistake into the global Python 3.13 (~40 MB on C:). Remove it with `python -m pip uninstall -y playwright`.

## How it works
- **Chrome:** the app launches `chrome.exe --remote-debugging-port=9333 --user-data-dir=D:\glabs_web\chrome-profile` if nothing answers on that port (path, profile and port are settings). The user signed in by hand once. Nothing types or stores credentials. The MCP uses the same port 9333, so it attaches to this Chrome instead of starting its own (its config points at a different profile).
- **App → MCP** (`src/web/flow_mcp.py`, `src/web/mcp_client.py`): a small stdio JSON-RPC client with no new Python dependency. It starts `node <web.flow_mcp_dir>\src\index.js`, does the MCP handshake, and calls `flow_connect` (open_flow false) once. Then each job calls `flow_generate_image` with prompt, model, ratio, count, download_size, reference_images, `campaign=labs-studio`, `auto_confirm=true` and a temporary output folder under `D:\glabs_web\flow_tmp`. The files are read back and the folder deleted. If Chrome was restarted, it reconnects once on `BROWSER_NOT_CONNECTED`. A dead server is restarted on the next job.
- **Flow is agent-driven (Oct 2026):** Flow lives at `flow.google.com`, and every generation goes through the project's agent chat. The upgraded MCP tool:
  - opens the campaign's project (`labs-studio` → the app's project `7a11ef03…`, registered in the MCP's `config/flow.projects.json`);
  - sets the project's **Agent settings**: aspect, count x1–x4, model, and "Confirm before generating: Never";
  - starts a new session, clears leftover ingredients, and uploads references as ingredients;
  - sends the prompt (with references: "Use the attached image(s) as reference. Create a new {aspect} image: …");
  - waits for the reply bubble to show its feedback bar;
  - downloads every option through **Download media → 1K Original size / 2K Upscaled**.
- **Error codes → queue:**

  | MCP error code | What the queue does |
  |---|---|
  | `NOT_LOGGED_IN`, `WRONG_GOOGLE_ACCOUNT`, `MANUAL_VERIFICATION_REQUIRED`, `GOOGLE_LIMIT_REACHED` | Non-retryable `ProviderError(stop_queue=True)` and Chrome is brought to the front |
  | `UNKNOWN_UI_CHANGE`, `MODEL_NOT_AVAILABLE`, `RATIO_NOT_AVAILABLE`, `INVALID_PARAMS`, `GENERATION_BUTTON_DISABLED`, MCP server not starting | Stop the queue |
  | `GENERATION_REFUSED` | Fails that job only |
  | Timeouts, download failures, `JOB_IN_PROGRESS` | Retryable |

  `JobQueue` calls `stop()` on any `stop_queue` error.
- **Pacing (app side):** one job at a time, a random 20–45 s gap, and a daily cap (default 60 prompts) counted in `web.usage.flow`. All configurable in Web Sessions.

## Changes to the google-flow MCP (outside the repo, not under git)
Backup taken first: `D:\Tools\google-flow-browser-mcp.bak-20261023` (without node_modules, the Chrome profile, outputs and logs), plus `config\*.bak-20261023`.
- `src/tools/generate-image.js` rewritten for the agent UI. New parameters: `count`, `download_size`, `wait_ms`, `timeout_ms`. `reference_images` now actually uploads. Images are full-size downloads instead of 512 px previews. Model and aspect are set in Agent settings, not asked for in prose. New error code `GENERATION_REFUSED`.
- `src/index.js`: new tool schema. Error responses now carry `error_code`, and sign-in, CAPTCHA and limit errors are flagged as blocking.
- `src/browser/connect.js`, `launch-profile.js`: attach to the Flow tab (`pickFlowPage`) instead of the first tab.
- `src/navigation/project-navigator.js`: a `campaign` now wins over "whatever project the tab is in".
- `config/flow.config.json`: image models are now Nano Banana 2.1 / Pro / 2 Lite (Imagen 4 is gone; "Nano Banana 2" is accepted as an alias for 2.1). `config/flow.projects.json`: a `labs-studio` entry.
- The other MCP tools (video, characters, scenes, Grid Architect) were not touched or tested.

## Testing on the real account (2026-10-23)
**1. MCP matrix**: 12/12 passed, calling the MCP directly (`mcp_matrix.py` in the session scratchpad; report at `D:\glabs_web\mcp_test\report.json`, images in `D:\glabs_web\mcp_test\<case>\`, contact sheet `D:\glabs_web\mcp_test\montage.png`).

| Case | Result |
|---|---|
| model "Imagen 4" | `MODEL_NOT_AVAILABLE` in 1 s, nothing spent |
| ratio 21:9 | `RATIO_NOT_AVAILABLE` |
| count 5 | `INVALID_PARAMS` |
| prepare only (auto_confirm false) | `ready_for_confirmation`, nothing generated |
| Nano Banana 2.1, 1:1, x1, 1K | 1 × 1024×1024, 52 s |
| Pro, 16:9, x2, 1K | 2 × 1376×768, 57 s |
| 2 Lite, 9:16, x3, 1K | 3 × 768×1376, 46 s |
| 2.1, 4:3, x4, **2K** | 4 × 2400×1792, 125 s |
| Pro, 3:4, x1, 2K, **1 reference** | 1 × 1792×2400, 83 s |
| 2 Lite, 16:9, x2, **2 references** | 2 × 1376×768, both references used (apple + ramen), 64 s |
| "Nano Banana 2" (old name) | treated as 2.1, 1 × 1024×1024 |
| 2 Lite, **4K** | `INVALID_PARAMS` "4K Upscaled is not available on this plan" (after generating; the page is now left tidy) |

Flow's own **Asset info** panel confirmed the model and aspect of each result (2.1 / Pro / 2 Lite as requested, 1:1 / 16:9 / 9:16 / 4:3 / 3:4) and showed the reference ingredients. Every image matches its prompt.

**2. App end to end** (`smoke_mcp.py`: real `GeneratorPage` + `JobQueue` + `WebFlowImageProvider` → MCP → Chrome, real settings with 20–45 s gaps; log `D:\glabs_web\smoke_mcp.log`, images in `D:\glabs_web\smoke_mcp\`):
- Batch A, Pro, 16:9, x2, 2K, 3 prompts (one with a reference): 3/3 done, each 2 × 2752×1536, 307 s.
- Batch B, 2 Lite, 9:16, x1, 1K, 2 prompts: 2/2 done, 768×1376, 125 s.
- Sign-in wall (a test campaign pointed at `flow.google.com/about`): job 2 failed with "Google Flow wants you to sign in…", the queue stopped, and jobs 1 and 3 ended **stopped**. Took 9 s.
- 4K through the MCP: `INVALID_PARAMS`, and afterwards the tab was back on the project grid.
- Daily usage went 3 → 8 (5 successful app jobs).

**3. Earlier, with the first (direct Playwright) version:** a 3-prompt batch and the Web Sessions tab's Check login / Diagnose, also on the real account.

**Not seen live:** a real CAPTCHA, a real usage-limit message and a policy refusal. The phrases matched for them are guesses, both in `BLOCKS` in the MCP's `generate-image.js` and in `src/web/selectors/flow.json` for the Web Sessions check.

## Layout and shared-file edits
- New: `src/web/{session,pacing,diagnose,mcp_client,flow_mcp}.py`, `src/web/adapters/{__init__,base}.py` (selectors, block and sign-in checks), `src/web/selectors/flow.json`, `src/gen/web_flow_image.py`, `src/ui/pages/web_sessions_tab.py`, `tests/test_web_provider.py`, `tests/test_web_flow.py`, `tests/test_mcp_client.py`, `tests/fixtures/fake_mcp_server.py`, `tests/fixtures/web/*.html` (stripped; account name and email replaced), `docs/03-web-automation-plan.md`, this doc.
- `src/gen/provider.py`: `ProviderError(..., stop_queue=False)`. `src/gen/queue.py`: stop the queue on `stop_queue` errors.
- `src/ui/generator/page.py`: optional `alternatives=[(provider, banner), …]` adds the Provider picker. The choice is saved at `pages.<page>.provider`, it rebuilds the config panel on switch, and it's locked while running. Pages without alternatives are unchanged.
- `src/app.py`: the image page gets `WebFlowImageProvider` as an alternative. `src/ui/pages/settings_page.py`: the Web Sessions tab.
- `src/config.py`: `web.*` defaults (Chrome path, profile, port, diag dir, MCP folder, node path, campaign, gaps, caps). `src/languages/en.py`: `web_*` keys and `gen_provider`.
- `packaging/labs_studio.spec`: bundles `src/web/selectors/*.json`. The frozen build was **not** rebuilt. It would also need Node and the MCP folder on the target PC.

## Known gaps
- The MCP folder isn't in any repo, so its changes exist only on this PC (plus the backup). If it is the GitHub project `TMSSS05/google-flow-browser-mcp` mentioned in its `summary.md`, the changes would need to go there separately.
- Other Claude sessions run their own google-flow MCP processes against the same Chrome. Each process has its own one-job queue, so an app batch and a Claude session generating at the same moment would fight over the tab. Run one at a time.
- 4K is checked only at download time, so a 4K request spends one generation before failing. The app only offers 1K/2K.
- With references the agent writes its own final prompt from yours. In the "ceramic sculpture" case it produced a gallery apple, not ceramic. That's the agent's interpretation, not something the app controls.
- Uploaded references stay in the Flow project's asset list.
- English Flow UI only. The webhook and workflow nodes don't have a Flow web provider of their own; the webhook uses whatever the image page has selected.

## Next
11b (Flow video) and 11c (ChatGPT images) can build on this. For 11b, the same Agent settings panel has video defaults (radiogroups 3/4: 16:9 / 9:16 and x1–x4; model "Omni 1.1 Flash"). The MCP's `generate-video.js` needs the same rework that `generate-image.js` got.
