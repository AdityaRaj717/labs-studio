# Spec: Productions page (plan S5-1)

Status: APPROVED by the owner 2026-11-04 with the decisions below.

## Objective
The solo video producer starts a whole Production (References, then Stills, then silent Animations, each stage held for review) from the app instead of asking an agent. Today only an agent can call `flow_production_plan` and `flow_production_start` (capability table A28, A29).

Success: the owner picks two files, sees exactly what the engine parsed and what it will cost, fixes errors, sets a cap, confirms, and lands on the sheet watching the Production's rows fill in from the engine.

## The page (new rail entry "Productions", `src/ui/production/page.py`)
1. **Files.** Moodboard file and prompts file pickers (paths stay as chosen; nothing copied).
2. **Plan.** "Check plan" calls `flow_production_plan` (free, no browser). Shows, as the engine returns them:
   - Cast (name, reference file or prompt), Shots in order (id, prompt, stage), parse errors with line numbers, `analysis_needed` questions, and the estimate in credits.
   - Errors block Start. Questions must be answered (or acknowledged) before Start.
3. **Settings.** `max_credits` (required when there are Animations; prefilled with ceil(estimate x 1.2), editable, never below the estimate), gates (References review on/off, Stills review on/off; both on by default), `reference_mode` (ingredient or character; default from the engine's config), Flow project (new, or one bound in S5-5), and a `cast_confirmed` tick: "I read both files and every Reference is exactly one subject".
4. **Start.** A confirm dialog stating shot count, estimate and cap. On yes, `flow_production_start` with `auto_confirm: true`; the app switches to the Flow Video (or Image) sheet, which already mirrors Production rows (run mirror, S2/S3).
5. Re-checking after a file edit replaces the shown plan; a stale plan (files changed since Check) disables Start until re-checked.

## Code
`production_actions.py` gains `plan(moodboard, prompts)` and `start(plan_id, cap, gates, reference_mode, project_url, cast_confirmed)`. Page widgets emit signals; the page calls the engine off the GUI thread like the generator page's `_act`. Strings in `src/languages/en.py`. Contact Sheet direction: no cards, red marker only on Start, three type sizes.

## Tests (offline, fake client)
`test_plan_errors_block_start`, `test_start_sends_cap_and_gates`, `test_start_needs_confirm`, plus `test_stale_plan_needs_recheck`. Run `.venv\Scripts\python.exe -m pytest`, `trail check`, then commit. Live proof: L5 with a budget the owner states.

## Boundaries
- Always: show only engine values; ask before any spend.
- Ask first: anything that changes the engine's plan or start contract.
- Never: approve Takes from this page; start without the confirm.

## Owner decisions (2026-11-04)
1. Own rail page "Productions"; also reachable from the Flow Video page (a "New Production" button that opens the page).
2. Default cap = estimate rounded up + 20% for regenerations, editable before Start (never below the estimate).
3. Past Productions stay only in the Runs tab; this page creates and configures new ones.
