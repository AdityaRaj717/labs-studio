# Phase 8 — Video Editor (spec)

The **Video Editor** sidebar page is a small non-linear editor. It is built for slideshows and short edits made from generated images and clips. ffmpeg renders everything. ffmpeg is an external binary that the user installs; Labs Studio never downloads or bundles it.

## Scope
- **Multi-track timeline.** Video tracks (full-frame, fitted and letterboxed), overlay tracks (positioned, scaled, semi-transparent images, clips and text) and audio tracks. A subtitle lane sits under them. Track order is the stacking order: the first video track is the bottom layer.
- **Clip edits.** Drag to move, including onto another lane of the same family (visual ↔ visual, audio ↔ audio). Drag an edge to trim; the left edge shifts the source offset. Edges snap to other clip edges and to the playhead. Split at the playhead (S), Delete, and Undo/Redo (Ctrl+Z / Ctrl+Y, up to 100 snapshots).
- **Clip inspector.** Start, duration, source offset, fade in/out, clip and track volume, loop source, position (x/y as 0–1 of the free space), width (fraction of the frame), opacity, and for text clips the text, size and colour.
- **Track header click** mutes an audio track or hides a visual one. Right-click the timeline to remove a track.
- **Subtitles.** Import SRT or ASS/SSA (UTF-8, UTF-16 or cp1252; tags stripped). Edit the cue table (start, end, text). Add a cue at the playhead, remove cues, and save them as SRT. The **style panel** sets font, size, colour, outline width and colour, shadow, bold, italic, bottom/middle/top position, edge margin and an optional background box with its own colour and opacity. Burning into the video can be switched on or off. Export can also write a sidecar `.srt`.
- **Overlays.** Image or video on an overlay track, plus **text clips** (Add text). Text clips are rendered as positioned ASS events in the same libass pass as the subtitles, so there is no drawtext or fontconfig setup on Windows.
- **Audio mix.** Every audio clip, plus the audio of video clips that have sound, gets trim, fades, clip × track volume and a delay to its timeline start. The streams are mixed with `amix normalize=0`, so levels are what the user set, then padded or trimmed to the project length. Music shorter than the video loops (`-stream_loop -1`).
- **Auto-edit / slideshow.** Takes a folder of images and clips, sorted naturally (img2 before img10). It sets seconds per image, an optional cap on clip length, and a crossfade (an alpha fade of each item over the previous one, with fades from and to the background at both ends). Optional music is looped under the whole video with a 2 s fade-out and its own volume. Clip audio can be kept or dropped. The project settings, subtitle style and cues are kept.
- **Project settings.** Resolution presets (1080p, 720p, 9:16, 1:1, 4K), fps and background colour. Projects save as JSON `*.lsproj`.
- **Preview.** An approximate Qt-drawn frame at the playhead showing images, overlays, text, fades and styled subtitles. Video clips show as a labelled tile. Play/Pause (Space) moves the playhead in real time, without audio. The export is the real render.
- **Export.** H.264 + AAC MP4 with a quality setting (CRF 18/21/26) and an encoder preset. It runs on a QThread with a progress bar from `-progress pipe:1`. **Cancel** sends `q` to ffmpeg, kills it after 2 s, and deletes the partial file. The dialog checks for missing source files first and shows the tail of the ffmpeg log if the export fails.

## ffmpeg
- The lookup order is the settings key `editor.ffmpeg_path` (a file, or a folder holding `ffmpeg.exe` or `bin/ffmpeg.exe`), then `PATH`. The path field, Browse and Check sit at the top of the page. If ffmpeg is missing, the bar shows a warning banner with the install hint (`winget install Gyan.FFmpeg`) and the Export button is turned off.
- Media is probed with `ffmpeg -i` (stderr parse), so ffprobe isn't needed.
- Graphs over 6000 characters are passed as `-/filter_complex graph.txt`, which needs ffmpeg 7+, so big slideshows don't hit the Windows command-line limit. ffmpeg runs in a work dir (`%APPDATA%\LabsStudio\editor\export`), so the `ass=subs.ass` filter gets a bare file name and needs no Windows-path escaping. The ffmpeg log is `ffmpeg.log` in that folder.

## Filter graph (one ffmpeg run)
Input 0 is `color=c=<bg>:s=WxH:r=fps:d=<total>`. Every image clip is `-loop 1 -framerate fps -t dur -i`, and every video or audio clip is `-ss in -t dur -i`. Each visual clip goes through `fps, trim, setpts, scale (+pad to the frame on video tracks), format=yuva420p, [colorchannelmixer aa], [fade alpha], setpts=PTS+start/TB`, then onto the running result with `overlay=…:eof_action=pass:enable='between(t,s,e)'`. The final chain is `ass=subs.ass,format=yuv420p`. Audio goes through `atrim, asetpts, aformat 48k stereo, afade, volume, adelay`, then `amix`, then `apad,atrim`.

## Layout
- `src/editor/` (no Qt): `model.py` (Project/Track/Clip/Cue/SubtitleStyle, edits, JSON), `subtitles.py` (SRT/ASS parse and write, `build_ass`), `autoedit.py` (`scan_folder`, `build_slideshow`), `ffmpeg.py` (find, probe, `build_export` → `ExportPlan`, `run_export`, `parse_progress`).
- `src/ui/editor/`: `page.py` (VideoEditorPage), `timeline.py`, `preview.py`, `panels.py` (ClipInspector, ProjectPanel, SubtitlePanel), `export.py` (ExportWorker, ExportDialog, AutoEditDialog). `__init__.editor_page` is the lazy factory.
- Shared files touched: `src/app.py` (one import and one `register_page` line) and `src/languages/en.py` (`ed_*` keys appended at the end). No new dependencies.

## Not built
Ken Burns/zoom on stills, transition types other than crossfade, audio ducking, waveform and thumbnail strips on the timeline, live video preview, and per-cue styles.
