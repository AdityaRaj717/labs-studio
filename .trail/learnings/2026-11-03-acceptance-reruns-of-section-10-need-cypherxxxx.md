---
title: Acceptance reruns of section 10 need sections 8 and 9 in the same run
author: CypherXXXX
date: 2026-11-03
branch: feat/ui-contact-sheet
cost: { minutes: 1, tokens: 5495 }
id: l-d67f1037
scope: repo
status: active
src: agent
touches:
  - src/ui/generator/sheet.py
  - src/ui/generator/take_panel.py
  - src/ui/help/page.py
  - tests/test_contact_sheet.py
  - tests/live/run_acceptance.mjs
  - docs/audits/unfinished-plan-tasks.md
---

## Watch out
run_acceptance.mjs --only is by section number and keeps state only within one invocation. Section 10 needs the character and scene made by 8 and 9; 19 needs the clip from 11. Use --only 8,9,10,11,13,18,19, not 10,11,13,18,19, or 10.1 fails with "needs sections 8 and 9".
In the code: tests/live/run_acceptance.mjs; docs/audits/unfinished-plan-tasks.md 2b.
