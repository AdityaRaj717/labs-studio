# Phase 11a handoff: browser core + Google Flow images (done 2026-10-23)

## State
- Phase 11a of `docs/03-web-automation-plan.md` is built on branch `claude/phase-11a-flow-images-a698ec`. Not merged, not pushed.
- `pytest`: 288 passed (260 before, 28 new in `tests/test_web_provider.py` and `tests/test_web_flow.py`). No browser in pytest: the provider and queue tests use a fake adapter, and the parser and block tests use HTML snapshots in `tests/fixtures/web/`.
- `python run.py` launches. The image page has a **Provider** picker: "Gemini API (image)" (as before) or "Google Flow web (image)". Settings has a new **Web Sessions** tab.
- New dependency: `playwright>=1.49` (in `requirements.txt` and `pyproject.toml`; installed in `.venv`, pip cache on `D:\tmp_render\pipcache`). Playwright's own browsers are **not** needed (no `playwright install`), because the app drives the installed Chrome over CDP. It was also installed by mistake into the global Python 3.13 (~40 MB on C:). Remove it with `python -m pip uninstall -y playwright` if you want the space back.

## How it works
- **Chrome:** `chrome.exe --remote-debugging-port=9333 --user-data-dir=D:\glabs_web\chrome-profile` (all configurable in Web Sessions). If something already answers on the port, the app attaches to it instead of launching. The user signed in by hand once. The app never types or stores credentials.
- **Threads:** Playwright's sync API is bound to one thread, so each site gets one worker thread with its own CDP connection and tab (`src/web/session.py`). A per-site lock holds the site for a whole job (cap check, gap, generate, count), so jobs on one site never overlap, whatever the page's thread setting.
- **Flow is agent-driven now (Oct 2026).** `labs.google/fx/tools/flow` redirects to `flow.google.com`. Inside a project, every generation goes through the agent chat; there is no direct image tool any more. Per job, the adapter (`src/web/adapters/flow.py`):
  1. opens the app's own Flow project (created on first use; URL kept in settings at `web.flow_project`)
  2. sets the agent's image defaults in Agent settings: aspect (1:1, 16:9, 9:16, 4:3, 3:4), count (x1–x4), model (Nano Banana 2.1 / Pro / 2 Lite), and **Confirm before generating = Never** in that project only, so the agent doesn't stop to ask
  3. starts a new chat session, clears leftover ingredients, uploads each reference through Add ingredients → Upload media, and sends the prompt
  4. polls the page HTML until the agent's reply bubble shows its feedback bar
  5. downloads every image option through Flow's own Download media → **1K Original size** (or **2K Upscaled**), then returns to the project
- **References:** when a job has references, the agent tends to treat it as an edit and keep the reference's shape. So the prompt is sent as `ref_prompt_template` ("Use the attached image(s) as reference. Create a new {aspect} image: {prompt}"). Without references it's sent unchanged.
- **Stopping:** `ProviderError` has a new `stop_queue` flag (it also forces `retryable=False`), and `JobQueue._run` calls `stop()` when it sees one. A sign-in wall, CAPTCHA, limit message, the daily cap or an unrecognised UI raise it, and the Chrome window is brought to the front. A prompt the agent answers without an image fails only that job, with the agent's reply as the error.
- **Pacing:** a random gap between jobs (default 20–45 s) and a daily cap per site (default 60 prompts; 0 = none). Usage is counted per submitted prompt in `web.usage.flow`.
- **Selectors:** every label and text match is in `src/web/selectors/flow.json`, so a Flow UI change should mean editing that JSON. **Diagnose page** in Web Sessions saves `screenshot.png`, `page.html`, `aria.txt` (accessibility tree) and `controls.json` to `D:\glabs_web\diag\flow-<time>\` and opens the folder.

## Manual smoke run (real account, 2026-10-23)
Run through the real `GeneratorPage` + `JobQueue` + `WebFlowImageProvider` + the app's `BrowserSession` (offscreen Qt), against the signed-in Chrome. Script: `smoke.py` in this session's scratchpad.
- **3 prompts, 1:1, x1, Nano Banana 2.1:** all 3 **done** in 242 s (about 50 s each plus 30–40 s gaps). They were saved as 1024×1024 JPEGs in `D:\glabs_web\smoke\out\20261023-174550\` and each matches its prompt (lighthouse watercolour, robot in a library, ramen). Montage: `D:\glabs_web\smoke\montage.png`.
- **Reference + 16:9 + x2 / x1, Nano Banana 2 Lite** (adapter run directly): x2 gave two images. The first try kept the reference's 1:1 shape, which led to the reference prompt template. With it, the result was 1376×768.
- **Sign-in wall:** with `web.flow_project` pointed at `flow.google.com/about` (what a signed-out user lands on), job 2 failed with "Google Flow wants you to sign in…", the queue stopped, and job 1 (waiting out its gap) ended **stopped**. Setting restored afterwards.
- **Web Sessions tab:** "Check login" returned signed in; "Diagnose page" saved a snapshot.
- **Not seen live:** a real CAPTCHA, a real quota/limit message, and a policy refusal. Their phrases in `flow.json` are guesses. The first time one happens, run Diagnose and fix the `block.*.text` lists.

## Layout and shared-file edits
- New: `src/web/{session,pacing,diagnose}.py`, `src/web/adapters/{__init__,base,flow}.py`, `src/web/selectors/flow.json`, `src/gen/web_flow_image.py`, `src/ui/pages/web_sessions_tab.py`, `tests/test_web_provider.py`, `tests/test_web_flow.py`, `tests/fixtures/web/*.html` (stripped of scripts and styles; account name and email replaced), `docs/03-web-automation-plan.md`, this doc.
- `src/gen/provider.py`: `ProviderError(..., stop_queue=False)`.
- `src/gen/queue.py`: stop the queue on `stop_queue` errors.
- `src/ui/generator/page.py`: optional `alternatives=[(provider, banner), …]` adds the Provider picker. The choice is saved at `pages.<page>.provider`, it rebuilds the config panel on switch, and it's locked while a batch runs. `set_provider(key)` does the same from code. Pages without alternatives are unchanged.
- `src/app.py`: the image page gets `WebFlowImageProvider` as an alternative.
- `src/ui/pages/settings_page.py`: the Web Sessions tab. `src/config.py`: the `web` defaults. `src/languages/en.py`: `web_*` keys and `gen_provider`.
- `packaging/labs_studio.spec`: bundles `src/web/selectors/*.json`. The frozen build was **not** rebuilt or tested with Playwright.

## Known gaps
- The webhook and workflow nodes still create pages and providers as before. The webhook submits to whatever provider the image page has selected. There is no `web_flow_image` workflow node yet.
- The agent sometimes words the reply or picks its own framing. The prompt goes in verbatim, but Flow's agent may still add to it. If results drift, tighten `prompt_template` in `flow.json` or use the project's "Agent instructions".
- With x2–x4 the agent decides how many options to return. The adapter downloads whatever comes back (checked for x2).
- Uploaded references stay in the Flow project's asset list (Uploads); nothing cleans them up.
- If Chrome is already open with the same profile but without the debugging port, the launch fails with a message telling the user to close it.
- Only English UI labels are matched. The Flow account must use English.

## Next
11b (Flow video) and 11c (ChatGPT images) can start from this branch once merged. For 11b, the agent settings already expose video defaults (16:9 / 9:16, x1–x4, model "Omni 1.1 Flash") in radiogroups 3 and 4.
