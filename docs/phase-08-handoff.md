# Phase 8 handoff — Video Editor (done 2026-10-21)

## State
- Everything in `docs/phase-08-video-editor.md` is built, on branch `claude/phase-8-video-editor-821d55`, which is not merged.
- `pytest`: 138 passed (91 before, 47 new). The new files are `tests/test_editor_model.py`, `tests/test_editor_ffmpeg.py` and `tests/test_editor_page.py`. Every subprocess call in them is mocked (fake `run` and `Popen`).
- `python run.py` launches. The **Video Editor** sidebar item opens the new page.
- **Manual export with real ffmpeg 9.0.2 (gyan full build, on PATH):**
  - In the real window: auto-edit of 4 images (2.5 s each, 0.6 s crossfades) + `music.mp3` (4 s, looped to 8.2 s) + an imported 2-cue SRT, exported through the Export dialog's worker thread. Result: 8.2 s 1280×720 H.264/AAC with burned-in subtitles, plus the `.srt` sidecar. Frames checked by eye.
  - A second render added a title text clip and a 20% semi-transparent logo overlay, and both show correctly.
  - Screenshots and renders are in `D:\tmp_render\phase8\` (`editor_window.png`, `export_dialog.png`, `e2e_sheet.png`, `sheet.png`). The scripts used a scratch `Settings` there and didn't touch `%APPDATA%\LabsStudio\settings.json`.
  - Speed: a 30-image, 89.5 s 1080p slideshow with 30 cues and music exported in 28 s. That graph is longer than 6000 characters, so it used the `-/filter_complex graph.txt` path.
  - Cancel: with 120 inputs, the export stops about 3 s after Cancel. While ffmpeg is still opening inputs it ignores `q`, so it gets killed after 2 s. The partial file is deleted.
- No new deps.

## Merge notes (phases 5/7/9 run in parallel)
- Shared files: `src/app.py` has `from src.ui.editor import editor_page` and `window.register_page("video_editor", editor_page)`. `src/languages/en.py` has an `ed_*` block appended before the closing `}`. Both are additive, so any conflicts are only about neighbouring lines.
- **ffmpeg helper**: mine is `src/editor/ffmpeg.py` (`find_ffmpeg`, `ffmpeg_version`, `probe`/`parse_probe`, `run_export`, `parse_progress`), with the setting key `editor.ffmpeg_path`. If Phase 7 has its own locator or setting, merge on one key (or read both) and one `find_ffmpeg`. The editor only needs `find_ffmpeg(configured)`, `ffmpeg_version`, `probe` and a progress-and-cancel runner.
- The ffmpeg path field is on the editor page itself, so the Settings page isn't touched. A Settings → Tools tab could reuse the same key later.

## Known gaps and notes
- The preview doesn't decode video (it shows a tile) and Play has no audio. Accurate output is export-only.
- Probing runs on the GUI thread (~50 ms per file). That's fine for normal folders but could lag for hundreds of videos.
- A crossfade between a narrow image and a wide one briefly shows the wider image in the pillarbox (alpha fade over the previous clip). Hard cuts are clean.
- `-/filter_complex <file>` needs ffmpeg ≥ 7. Older ffmpeg works only for short graphs (≤ 6000 characters).
- Text clips use the subtitle style's font, bold setting and outline, with their own size, colour and position.

## Next
- At merge: reconcile the ffmpeg helper with Phase 7.
- Optional: Ken Burns on stills, more transition types, ducking music under clip audio, waveform and thumbnail strips, and a "render frame at playhead" preview through ffmpeg.
