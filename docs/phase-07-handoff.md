# Phase 7 handoff: Video tools (done 2026-10-21)

## State
- Everything in `docs/phase-07-video-tools.md` is built on branch `claude/phase-7-video-tools-43067d`. `pytest`: 117 passed (91 before, 26 new in `tests/test_tools.py` and `tests/test_tool_pages.py`). Tests never start a process: the runner gets a fake Popen and providers get a fake `run`/`capture`, so they pass without ffmpeg or Real-ESRGAN installed.
- `python run.py` launches with no errors in the log. **Video Cut** and **Image Upscaler** are real pages now, and Settings has a **Tools** tab.
- No new deps.

## Manual checks (ffmpeg 9.0.2 from winget, on PATH)
Sample: a 12 s 640×360 testsrc2 + sine clip at `D:\tmp_render\phase7\sample.mp4` (generated with ffmpeg). Outputs are in `D:\tmp_render\phase7\out` and `app_out`.
- Slicer, fixed 5 s, stream copy: 3 pieces of 5.07 / 5.17 / 2.0 s. Copy cuts land on keyframes, as expected.
- Slicer, ranges `0:02-0:04.5, 0:10-`, re-encode: 2.5 s and 2.0 s, exact.
- Frame extractor: every 2 s → 6 PNGs; 3 evenly spaced JPGs; last frame; first frame (640×360).
- Stop: a long 1080p60 encode was killed 2.2 s after the stop flag, and no ffmpeg.exe was left running.
- Real window (temp settings file; `%APPDATA%\LabsStudio\settings.json` untouched): slicer batch ran to Done, 3 files. Screenshots: `D:\tmp_render\phase7\shot_slicer.png`, `shot_frames.png`, `shot_upscaler.png`, `shot_settings_tools.png`.

## Not verified
- **Real-ESRGAN itself never ran.** It isn't installed, and the rules say not to download it, so the Upscaler page currently shows the "Real-ESRGAN not found" banner. The command line, `NN.NN%` progress parsing, the output name and the compare dialog are covered by tests with a fake run that writes a real image. To check it for real: put `realesrgan-ncnn-vulkan.exe` and its `models` folder somewhere, set the path in Settings → Tools, and upscale one image.
- Whether the ncnn build prints `%` progress on every tile or only at the end. If only at the end, the bar jumps from 0 to 99 and then to Done.

## Notes for later phases / merge
- Shared-file edits are small and additive: `src/app.py` `register_pages` (2 imports + 2 lines after the settings line), `src/ui/pages/settings_page.py` (1 import + 1 `addTab` after the keys tab), `src/languages/en.py` (keys appended under `# Phase 7: video tools`). When merging with phases 5/8/9, expect trivial conflicts at these append points; keep both sides.
- `ToolPage` (`src/ui/tools/tool_page.py`) is a generic "list of input files → external-binary job" page on `JobQueue`. Phase 8 (editor) can reuse `src/tools/runner.run_command`, `binaries.find_binary("ffmpeg")` and `ffmpeg.progress_seconds` for exports.
- Tool providers write straight to disk and return `[]` from `generate`. The queue's saver is `provider.take_outputs`.
- Progress bars are per-row `QProgressBar` cell widgets styled from `theme.COLORS`. They pick up the theme in force when the row is created, so after a theme toggle only new rows change colour.

## Next
Stop here (Phase 7 only). The phase 5/8/9 branches merge separately.
