# UI performance baseline, 2026-11-04 (S6-1)

Machine: AMD Ryzen 7 6800H, 15.3 GB RAM, Radeon 680M iGPU plus RTX 3060 Laptop, Windows 11 (10.0.26300), Python 3.12.10.
Command (repo root): `.venv\Scripts\python.exe tools\perf_ui.py 2000 240 docs\perf\baseline-2026-11-04.json`
Setup: 2000 rows, frame width 240, window 1920x1080, real `MainWindow` built offscreen (`WA_DontShowOnScreen`, as `tools/qa_shots.py`). Images: 1376x768, 1 PNG in 3 and JPEG q90 otherwise, 24 base files hard-linked to 2000 distinct paths. 70% of rows done with an output, the rest failed, running or pending. No network, no Flow. Not part of pytest. One run takes about 5 to 8 minutes.

| Metric | Measured | Target | Meets |
|---|---|---|---|
| Cold start to window shown | 2.25 s | 1.5 s or less | no |
| First build of a page (video page) | 359 ms | 200 ms or less | no |
| Import 2000 rows | 116 ms | 500 ms or less | yes |
| Filter change (mean of 6) | 2076 ms | 50 ms or less | no |
| Scroll frame p95 | 5316 ms | 20 ms or less | no |
| Scroll frame worst | 7789 ms | 40 ms | no |
| Slider drag | 0.58 fps | 30 fps or better | no |
| Slider drag, no decode on UI thread | null | none | not measured |
| 100 job updates per second, UI thread busy | 99.6% (only 13 updates ran in 7.5 s) | under 10% | no |
| Thumbnail memory by bytes | null | 256 MB cap | not measurable |
| RSS after scrolling the whole sheet | 153 MB (134 MB before) | 600 MB or less | yes |
| 20 viewer opens and closes, RSS growth | 29.4% (185 to 239 MB) | under 5% | no |

How each is measured, and limits:
- Cold start is script start (imports and demo setup included) to window shown and first `grab()`, warm disk cache, offscreen. Synthetic image creation is subtracted.
- Pages are built lazily and the window opens on the image page, so its build is inside cold start. The first-build number is the video page, the same `GeneratorPage` class.
- Scroll and slider frames are one scrollbar or slider step plus a synchronous viewport repaint plus event processing. They are not display refresh intervals. The JSON also holds the paint-event intervals.
- The burst fires `model.refresh_job` every 10 ms; busy is time inside `processEvents` over wall time. The UI was so slow that the timer ran about 2 times per second, so 99.6% means the thread never idled, not that 100 updates per second were absorbed.
- Slider "no decode on UI thread" and thumbnail bytes are null: the app has no counter or byte accounting, and this task changes no app code.
- Variance is large on the slow items: an earlier run gave filter 7.6 s, scroll p95 7.6 s, slider 0.44 fps, cold start 2.2 to 2.9 s, first build 359 to 663 ms. Read the order of magnitude, not the digits.
- One run, one machine, offscreen painting. No target was changed.
