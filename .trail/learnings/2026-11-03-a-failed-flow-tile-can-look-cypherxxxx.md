---
title: A failed Flow tile can look like a whole-page block and keeps matching until deleted
author: CypherXXXX
date: 2026-11-03
branch: feat/ui-contact-sheet
cost: { minutes: 1, tokens: 5495 }
id: l-c2e7adaa
scope: repo
status: active
src: agent
touches:
  - src/ui/generator/sheet.py
  - src/ui/generator/take_panel.py
  - src/ui/help/page.py
  - tests/test_contact_sheet.py
  - docs/audits/unfinished-plan-tasks.md
---

## Watch out
A per-tile failure that says "unusual activity" and "You have not been charged for this generation" sits in the project grid and stays there. The block detector matches page text, so every later poll on that project reads it as a WAF block again until the tile is deleted (trash icon). Seen in acceptance project 065acc3b (y0-2026-11-02). credits_at_risk was reported true although the tile says not charged and the balance did not move (792 through accept3).
## Decided (proposed, not applied)
Treat a per-tile message as a retryable generation failure; keep the full-page WAF block only for whole-page interstitials. Confirm against a screenshot of a real interstitial first.
In the code: mcp/google-flow/src detectBlock; evidence docs/audits/unfinished-plan-tasks.md section 2.
