# Build plan — "Labs Studio" clone

Stack: Python 3.12+, PySide6, ffmpeg (system binary), Pillow, openpyxl, httpx.
Providers (official APIs, user's own keys): Google Gemini API (Imagen images, Veo video, Gemini TTS voices), OpenAI Images API, xAI API (Grok image/video).

Each phase is built in its own session and kept under ~300k context. A phase is done when the app launches, the new page works end to end, and `pytest` passes.

| # | Phase | Done when |
|---|---|---|
| 1 | **App shell**: package layout, main window, collapsible sidebar, page router, dark/light theme tokens, settings store (`%APPDATA%\LabsStudio\settings.json`), i18n scaffold (en), log panel, splash | App opens, every sidebar item routes to a placeholder page, theme and settings persist |
| 2 | **Generator framework**: reusable config panel, prompt table model/view, prompt import (txt/xlsx/paste), ref-folder auto-match, queue manager (threads, delay, pause/stop/retry), output saving, stats header. Ships with a fake provider for tests | A fake job batch runs through the queue with live row status |
| 3 | **Image page (Gemini/Imagen)** + Settings → API keys tab | Real images generated and saved from a prompt list |
| 4 | **Video page (Veo)**: t2v, i2v start/start+end, duration/resolution, long-running op polling, download | Real clips generated in batch |
| 5 | **OpenAI Image page** and **Grok page** (t2i, i2i, t2v) on the same framework | Both pages generate |
| 6 | **Characters library** (name, ref images, voice from Gemini TTS list) wired into the image/video pages | A character can be attached to prompts |
| 7 | **Video tools**: slicer, frame extractor, Real-ESRGAN upscaler with compare dialog | Each tool processes a sample file |
| 8 | **Video editor**: multi-track timeline, SRT/ASS subtitles with style panel, overlays, audio mix, auto-edit/slideshow, export | A slideshow with subtitles and music exports |
| 9 | **Workflow node editor**: graph scene, nodes for each generator and tool, runner | A 3-node chain (prompt → image → video) runs |
| 10 | **Webhook API** (local HTTP job submit) + stats tab + packaging (Nuitka or PyInstaller) | External `curl` submits a job; installer builds |

Phases 5, 7, 8 and 9 depend only on phase 2 (and 3 for patterns), so they can run in parallel sessions after phase 3.
