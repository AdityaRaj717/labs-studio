# Phase 7 spec: Video tools

Plan row: **Video tools**: slicer, frame extractor, Real-ESRGAN upscaler with compare dialog. Done when each tool processes a sample file.

## Scope
- **Video Cut** page (sidebar `video_cut`) with two tabs: **Slicer** and **Frame extractor**, both on ffmpeg/ffprobe.
- **Image Upscaler** page (sidebar `upscaler`) on Real-ESRGAN (`realesrgan-ncnn-vulkan`), with a before/after **compare dialog**.
- **Settings → Tools** tab: a path for ffmpeg, ffprobe and Real-ESRGAN. Blank = PATH.

## External binaries
- The app never downloads or bundles a binary. The user installs ffmpeg (e.g. `winget install Gyan.FFmpeg`) and Real-ESRGAN ncnn-vulkan (the release zip from the Real-ESRGAN GitHub, which includes the `models` folder) themselves.
- Lookup order (`src/tools/binaries.py`, `find_binary`):
  1. `tools.<id>_path` in settings (`ffmpeg`, `ffprobe`, `realesrgan`). This can be the exe or the folder holding it.
  2. ffprobe only: next to a configured ffmpeg.
  3. `shutil.which` (`ffmpeg`, `ffprobe`, `realesrgan-ncnn-vulkan`, `realesrgan`).
- If a binary is missing, the page shows a banner ("X not found. Install it and add it to PATH, or set its path in Settings → Tools…") and Start is disabled. The check runs again each time the page is shown, so after fixing the path in Settings you can go back and start straight away.

## Shared page behaviour (`ToolPage`)
- One row per input file. Add files, add a folder (only matching extensions are added; duplicates are skipped), drag-and-drop files or folders, Remove selected, Clear.
- Options come from `ConfigPanel` (Phase 2), saved at `pages.<key>.*`. The rows that only matter for one mode are hidden (`visible_when`).
- Common options: concurrent threads (1–4, default 1) and save folder (default `AppData/LabsStudio/outputs/<key>`).
- Start runs pending/failed/stopped rows through the Phase 2 `JobQueue` on worker threads (no auto-retry). Stop kills the running process(es) and marks queued rows stopped. Each row shows its status, a progress bar, and its output or error. Double-clicking a row opens its output file, or its folder when there are several.
- Outputs never overwrite: per-video folders and file names go through `unique_path` (`clip_slices`, `clip_slices-1`, …).

## Slicer
| Option | Values |
|---|---|
| Split by | Fixed length (piece length, s) / Equal parts (N) / Custom ranges (`0:05-0:12, 1:00-`; an open end means to the end of the clip, and ends are clamped) |
| Method | Stream copy (fast and lossless; each piece starts on the nearest keyframe) / Re-encode H.264 + AAC (exact cut, CRF 0–51, default 18) |

- ffprobe reads the duration first. In fixed-length mode, a last piece under 0.25 s is joined to the one before it.
- One ffmpeg call per piece: `-ss <start> -i in -t <len> -map 0:v:0 -map 0:a?`. MP4/MOV/M4V get `+faststart`. Copy mode adds `-avoid_negative_ts make_zero` only for non-MP4 containers: in MP4 that flag exposes the keyframe pre-roll (a 5 s piece came out 10 s on the test clip), while the default edit list trims it.
- Output: `<save>/<stem>_slices/<stem>_part001_0m05.000s.<ext>`. Copy keeps the source container; re-encode writes `.mp4`.
- Progress comes from `-progress pipe:1` `out_time_us`, summed across the pieces.

## Frame extractor
| Mode | ffmpeg |
|---|---|
| One frame every N s | `-vf fps=1/N` → `<stem>_000001.png` … |
| N evenly spaced frames | one `-ss t -frames:v 1` per frame, at `duration*(i+0.5)/N` |
| Every frame | `-fps_mode passthrough` |
| First frame | `-ss 0 -frames:v 1` |
| Last frame | `-sseof -3 … -update 1` (the last write wins) |
| At timestamps | `0:01, 12.5 …`, clamped to the clip length |

- Format: PNG or JPG. JPG quality 1–100 maps to `-q:v` 31–2.
- Output: `<save>/<stem>_frames/`.

## Image Upscaler
| Option | Values |
|---|---|
| Model | `realesrgan-x4plus` (photo, 4×), `realesrgan-x4plus-anime` (4×), `realesr-animevideov3` (2/3/4×; the Scale row only shows for this model) |
| Output format | png / jpg / webp |
| Tile size | 0 = auto (`-t`) |
| TTA | `-x` |

- Command: `realesrgan-ncnn-vulkan -i in -o out -n model -s scale -f fmt [-m <exe dir>/models] [-t] [-x]`, run with cwd = the exe's folder. Progress comes from the `NN.NN%` lines.
- Inputs: png/jpg/jpeg/webp/bmp. Output: `<save>/<stem>_x<scale>.<fmt>`.
- **Compare**: select one finished row and press Compare, or double-click it. The dialog shows the upscale with the original stretched to the same size. You drag on the image or use the slider to move the divider, and the labels show both pixel sizes.

## Module layout
- `src/tools/` (Qt-free): `binaries.py`, `runner.py` (`run_command`: streams merged stdout/stderr lines, kills on stop, raises `ProviderError` on a non-zero exit; `capture` for ffprobe), `ffmpeg.py` (parsing, planning, commands), `realesrgan.py`, `tasks.py` (`ToolProvider` + `SlicerProvider`, `FrameExtractorProvider`, `UpscaleProvider`).
- `src/ui/tools/`: `tool_page.py`, `video_cut.py`, `upscaler.py`, `compare.py`, `settings_tab.py`.
- Shared files touched (additive only): `src/app.py` (2 imports + 2 `register_page` lines), `src/ui/pages/settings_page.py` (1 import + 1 `addTab`), `src/languages/en.py` (keys appended under `# Phase 7`). No new deps.
