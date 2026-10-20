# G-Labs Studio — what the app is (reverse-engineering summary)

Target: `C:\Program Files\G-Labs Studio\G-LabsStudio.exe` (106 MB). REA evidence: `ev_4f65ede8…b00e8`.
Raw string dumps (outside the repo): `D:\tmp_render\glabs\strs\<module>.txt`.

## Tech stack (observed)
- Python 3.12 compiled with **Nuitka** (standalone).
- UI: **PySide6 / Qt 6** Widgets, dark/light themes, collapsible sidebar, splash screen, update checker.
- Media: ffmpeg libs, Pillow (+HEIF), numpy; openpyxl for Excel prompt import.
- 14 UI languages; settings in `%APPDATA%\G-Labs Studio\settings.json`, one section per page.

## Pages (sidebar order, from the `nav_*` strings)

| Sidebar | What the user does there |
|---|---|
| Flow Image | Batch text→image and ref-image→image, aspect ratio, images per prompt, upscale |
| Flow Video | Batch text→video, image→video (start / start+end frames), reference/"ingredients" video, duration, resolution, voice choice, character library |
| Grok Imagen | Text→image, image→image, text→video, compose tabs |
| OpenAI Image | Text/ref → image (quality, aspect, count) |
| Meta Vibes / Meta Muse / Google Vids / Google Pics | Same batch-queue pattern against other generators |
| Characters | Saved characters (name + reference images + voice) reused across prompts |
| Workflow | Node-graph editor (nodes, sockets, edges, groups, undo) that chains generation steps |
| Video Editor / Studio | Multi-track timeline, subtitles (SRT + styled ASS), overlays, audio mix and fades, auto-edit/slideshow, CapCut export |
| Video Cut tools | Video slicer, frame extractor |
| Image Upscaler | Real-ESRGAN upscaling with a before/after compare dialog |
| Webhook API | Local HTTP server so outside tools can submit jobs |
| Settings | Accounts/API keys, tools, stats, logs, language, theme |

## The shared "generator page" pattern (most of the app)
Every generator page has the same skeleton, and that skeleton is the core of the clone:
1. **Config panel:** model, aspect ratio, resolution, duration, count per prompt, concurrent threads, random delay min/max, save folder + subfolder mode, reference-image folder.
2. **Prompt table:** one row per prompt with prompt text, attached refs, status, progress and an output thumbnail. Drag-drop, an empty-state hint, per-row edit dialog.
3. **Prompt import:** paste, `.txt` (one per line / blank-line separated), `.xlsx`.
4. **Reference auto-match:** image filenames in the ref folder are matched to prompts by keyword.
5. **Queue manager:** thread pool, pause/resume/stop, per-row retry, logs, a stats header (done/failed/running).
6. **Output:** files saved to `save_dir[/subdir]`, preview popup, open folder.

Video-editor settings seen: fixed/random clip length, ratio and fill (pad/crop), overlay with opacity/blend, subtitle style (font, size %, colors, outline, shadow, box, position %), sound (original/added volume, loop, fade in/out).

## What the clone will NOT reproduce
The original drives several services through users' logged-in web sessions using unofficial means: many accounts at once, proxy rotation, bot-check workarounds, and stripping provider watermarks. The clone leaves all of that out. It uses each provider's **official API with the user's own API key**, and it keeps provider watermarks and provenance marks.
Assets (style sample images, voice preview clips) are the original's property and are not copied.
