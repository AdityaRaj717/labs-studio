---
title: A bare apad filter makes ffmpeg spin forever on export
author: CypherXXXX
date: 2026-11-03
branch: feat/ui-contact-sheet
cost: { minutes: 9, tokens: 18749 }
id: l-c4a5b5b0
scope: repo
status: active
src: agent
touches:
  - docs/audits/capability-audit.md
  - docs/audits/unfinished-plan-tasks.md
  - docs/superpowers/plans/2026-11-03-labs-studio-master-plan.md
  - docs/superpowers/specs/2026-11-02-youtube-production-design.md
  - help/en/flow-image.md
  - help/en/getting-started.md
  - help/en/img/characters.png
  - help/en/img/flow-image.png
  - help/en/img/log.png
  - help/en/img/main-window.png
---

## Decided
Pad audio with apad=whole_dur=<seconds> followed by atrim, never a bare apad. A bare apad never ends the stream, so ffmpeg 9.0.2 kept running and the export hung (7 of 30 runs of test_bgm_ducks_under_voice). After the fix: 30 of 30.
## Watch out
run_export also has stall_seconds (120): if no progress line arrives for that long, ffmpeg is killed and ExportError is raised. Keep it; a user export must never hang.
In the code: src/editor/ffmpeg.py run_export, tests/test_ffmpeg_watchdog.py.
