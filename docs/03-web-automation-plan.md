# Build plan — web-session providers (Google Flow, ChatGPT web)

Goal: use the user's own subscriptions (Google AI Pro, ChatGPT Go) from the app by driving the web apps in a real browser, alongside the existing API-key providers.

Stack addition: Playwright for Python (`playwright`), attached over CDP to a real Chrome install.

## Ground rules

- Google's and OpenAI's consumer terms restrict automated access to their web apps. The risk is to the user's own paid account (flagging, rate limits, suspension), so the design behaves like one person on one account.
- One account per site, one job at a time per site, randomized gaps between jobs, a user-set daily cap.
- The user logs in by hand in a visible Chrome window. The app never stores or types passwords.
- Out of scope, as before: CAPTCHA or bot-check workarounds, multi-account or proxy rotation, watermark stripping.
- On a CAPTCHA, sign-in wall or "limit reached" message the job stops with a non-retryable `ProviderError` and the browser window is brought to the front.

## Architecture

New package `src/web/`:

| File | Role |
|---|---|
| `session.py` | Launches Chrome (`chrome.exe --remote-debugging-port=<port> --user-data-dir=D:\glabs_web\chrome-profile`, path configurable) or attaches to it if running, then `connect_over_cdp`. One tab per site, a per-site lock so jobs run serially, login check, bring-to-front |
| `adapters/base.py` | `SiteAdapter`: `is_logged_in()`, `submit(prompt, refs, opts)`, `wait_done(timeout)`, `collect() -> list[bytes]`, `detect_block() -> str or None` (captcha / login / quota) |
| `adapters/flow.py` | Google Flow: open or create a project, pick mode (image / video), model, aspect, count, upload refs, submit, poll the tile grid, download via Flow's own download action |
| `adapters/chatgpt.py` | ChatGPT web: new chat, attach refs, send, wait for the image to finish, fetch the full-size image through the page's request context |
| `selectors/flow.json`, `selectors/chatgpt.json` | Every selector and UI text match lives here, so a site UI change is a JSON edit |
| `diagnose.py` | Saves a screenshot and the accessibility tree of the current tab to `D:\glabs_web\diag\<site>-<time>\` |
| `pacing.py` | Random gap between jobs, daily counter per site persisted in settings |

Providers in `src/gen/` built on the existing `Provider` interface (`src/gen/provider.py`): `web_flow_image`, `web_flow_video`, `web_chatgpt_image`. They plug into the queue, workflow nodes, characters and webhook unchanged.

UI: a **Web Sessions** tab (Settings or its own sidebar item) with one row per site: Launch browser, logged in ✓/✗, used today / daily cap, Diagnose page. Generator pages get the new providers in their provider picker.

## Phases

Each phase is built in its own session and kept under ~300k context. A phase is done when the app launches, the feature works end to end on the real account, and `pytest` passes.

| # | Phase | Done when |
|---|---|---|
| 11a | **Browser core + Flow images**: `session.py`, adapter base, pacing, diagnose, Flow adapter (image mode: model, aspect, count, refs), `web_flow_image` provider, Web Sessions tab, settings for Chrome path / profile dir / port / caps | A prompt list on the image page generates and saves Flow images through the logged-in browser; quota and login-wall paths stop the queue cleanly |
| 11b | **Flow video (Veo)**: video mode, t2v and frames/i2v, duration and aspect, long polling, credit-cost warning, `web_flow_video` provider | Real Flow clips generated in batch from the video page |
| 11c | **ChatGPT images**: ChatGPT adapter and `web_chatgpt_image` provider, reusing the 11a core | A prompt list generates and saves images from ChatGPT web |
| 11d | *(optional)* **Gemini app** (gemini.google.com) adapter as a fallback for images/video if Flow's UI proves too unstable | Same as 11a/11b for the Gemini app |

11b and 11c both depend only on 11a and can run in parallel sessions after it.

## Testing

- Adapter parsing and block detection against saved HTML snapshots in `tests/fixtures/web/`.
- Provider and queue behaviour with a fake `SiteAdapter`, so no browser is needed in `pytest`.
- One manual smoke run on the real account at the end of each phase, recorded in that phase's handoff doc.

## Known limits

- Flow video spends the monthly AI credits quickly; show cost per job before a batch.
- ChatGPT Go image limits are lower than Plus; the daily cap matters.
- Expect selector fixes when the sites change their UI; `diagnose.py` plus the JSON selectors keep those small.
