# UI direction: Grading suite (2026-11-05)

Scope: whole app shell and Flow Image / Flow Video review surface (Operate). Native PySide6, Windows. Replaces the Contact Sheet world (2026-11-05, owner chose "Grading suite").

## Direction contract
THESIS: a grading suite for takes: pictures judged on calibrated neutral grey, decisions made by key and shown as glyphs. Refuses the generic dark SaaS table and the black-void gallery with a gimmick overlay.
OWN-WORLD: graphite chrome (rail and panel headers a step darker than panels), cells on neutral grey with no colour cast (dark #474747, light #b9b9b9; Lightroom-style surround, not a true 18% card, which glares in a dark room), hairline 1 device-px separators, radius 2. One accent (decision orange-red) on primary action and flags only; amber = live only; rose + hatch = failed only; star yellow-neutral for ratings; 5 colour labels (red, yellow, green, blue, purple, as Lightroom) as dots. Segoe UI Variable 11/13/20, tabular numerals in Cascadia Mono for frame data only.
STORY: producer scans the sheet, marks takes with P/X/1-5/6-9 without leaving the keyboard, filters by counts, retries or approves; spend always gated by confirm.
FIRST VIEWPORT: rail 200px left (collapsible), run bar 44px header (title, credit meter, RunStrip, Start primary), tool row 36px (import/paste icons, Sheet/Queue segmented, filters with counts, density, size slider), centre grid of cells on mid-grey with index number faint top-left, flag/stars/label row under picture, state dot top-right; right Inspector with a 28px header bar per section, collapsible sections, right-aligned label/value rows.
FORM: category standard (canon) at Resolve/Lightroom craft, owner pinned it. seed:f81ea78990d39c93
Signature interaction: L cycles lights (full, dim 70%, out) dimming all chrome around the selected take; J cycles cell density (picture only, compact, expanded). Ctrl+K action panel for the selected take with shortcuts right-aligned. Motion: 120-160 ms ease-out on hover/selection/dim; no bounce; off when Windows animations are off.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance


Repo D:\Prog\labs-studio-dev, branch feat/ui-contact-sheet. PySide6. Do NOT touch mcp/google-flow/ or the engine. Never stage mcp/google-flow/README.md. Do not commit (main agent commits).
UI text through src/i18n.py `tr()` and src/languages/en.py. Offline tests: `.venv\Scripts\python.exe -m pytest -q -x --timeout 300` (skip tests/test_stitch.py if it hangs; known flaky).

## 1. Tokens (src/theme.py COLORS) — replace values; keep every existing token name; add new ones to TOKEN_NAMES
Dark:
 sidebar #1b1b1d (rail), rail_text #dcdcdc, rail_muted #8c8c8c, rail_hover #262628, rail_selected #303033, rail_border #141416
 header #222224 (NEW: panel header bars, run bar, tool row)
 panel #29292b (Inspector, dialogs), raised #333336, bg #2f2f2f (sheet ground behind cells)
 cell #3a3a3a (NEW: cell surround, neutral mid-grey), cell_hover #434343 (NEW), cell_selected #4d4d4d (NEW)
 text #e4e4e4, text_muted #9b9b9b, faint #5e5e5e (NEW: big index numerals)
 border #19191a (hairlines, darker than panels), border_strong #4a4a4c, hover #38383b, selected #424245, input_bg #1f1f21, scrollbar #4a4a4c
 accent #e5562b, accent_text #ffffff, marker = accent (#e5562b), live #f0a417, failed #e46c8c, done #e4e4e4
 star #e2e2e2 (NEW), star_empty #5a5a5a (NEW)
 label_red #d64a3e label_yellow #d6b23c label_green #52a35c label_blue #4180d0 label_purple #8c62c8 (NEW)
 frame/frame_text/frame_muted: keep names, set frame = cell value, frame_text = text, frame_muted = text_muted (viewer/splash still use them)
Light ("lights up"):
 sidebar #d4d4d6, rail_text #1c1c1c, rail_muted #5c5c5c, rail_hover #c8c8ca, rail_selected #bdbdc0, rail_border #c2c2c4
 header #dadadc, panel #e6e6e8, raised #f1f1f2, bg #a9a9a9, cell #b9b9b9, cell_hover #c3c3c3, cell_selected #cdcdcd
 text #161616, text_muted #4f4f4f, faint #8f8f8f, border #c4c4c6, border_strong #8a8a8c, hover #d0d0d2, selected #c4c4c7, input_bg #f6f6f7, scrollbar #9a9a9c
 accent #c8401a, marker #c8401a, live #9a5e00, failed #b3164f, done #161616, star #1c1c1c, star_empty #8c8c8c, labels same as dark
Fonts: UI_FONT unchanged; TITLE_FONT = '"Segoe UI Variable Display", "Segoe UI"' weight 600; DATA_FONT unchanged (numerals and frame data only).
Sizes: three only: 11 (labels, cell data), 12 (body, controls), 15 (page title). Replace 13 -> 12 and 20 -> 15 in QSS and any setPixelSize in src/ui.

## 2. Stylesheet (build_qss)
- No outlined buttons. QPushButton secondary: background raised, no border, radius 2, height 26, padding 0 10; hover = hover token; pressed = selected; disabled text faint. Primary (existing objectName/property used for Start): accent fill, accent_text, hover lighten ~8%.
- Tool buttons/icon buttons: transparent, hover fill hover token, checked fill selected token, radius 2.
- Run bar, tool row and every panel header: background header token, 1px bottom border token. Page title 15px semibold.
- Tabs (Inspector Take/Settings/Runs/Audio/Assets): flat; selected = text colour + 2px accent bottom bar is NOT allowed (accent is decisions only) -> selected = text colour + 2px text-colour bottom bar; unselected text_muted.
- Filter buttons in the tool row: flat toggle buttons, checked = selected fill + text colour; count shown in text_muted after the label ("To review 5" with the number in DATA font if feasible, else plain).
- Tables (queue): no zebra, header row header token with 11px text_muted sentence case, 1px border hairlines, selected row = selected token (failed rows keep failed text colour when selected: current tests cover this).
- Scrollbars 8px, handle scrollbar token, radius 2, no arrows. Selection colour in inputs = selected token. Focus ring: 1px text_muted outline on focusable inputs.
- No gradients, no shadows at rest, no pills, no glow. Radius 2 everywhere.

## 3. Sheet cell (src/ui/generator/sheet.py SheetDelegate) — Lightroom-style cell
Remove the ring and cross drawing and its animation (draw_ring, draw_cross, ring_points, ring_path, RING_MS, ring_progress, draw_ring_on and callers in page.py, viewer.py, splash.py). Update/remove tests that test them (tests/test_contact_sheet.py etc.) and say so.
Cell = rect filled with `cell` token (hover cell_hover, selected cell_selected + 1px `text` outline inset). Padding 8px.
Density (view.density: 0 picture, 1 compact (default), 2 expanded):
- 0: picture only, letterboxed centred in padded area; state dot only.
- 1: picture area, then a 22px bottom row: left = flag glyph (approved: filled flag icon in accent; rejected: x icon in accent; else nothing) then rating stars (5 small 9px stars, filled `star`, empty `star_empty`; draw only if rating>0 OR cell hovered/selected), then colour-label 8px square dot if label; right = state text 11px text_muted (live: amber, percent/elapsed exactly as today's progress_view logic; failed: failed colour; stale prefix as today).
- 2: as 1 plus a 20px top row: index number `{job.index}` 15px weight 300 in `faint` at left, ident (item id, +outputs, take badge, agent) 11px text_muted after it, elided.
- compact (1) shows index as 11px data-font faint at top-left inside padding over the cell (not over the picture).
State dot top-right of the cell 7px circle: live amber (running/regenerating), failed rose, nothing otherwise.
Rejected: picture drawn at 45% opacity. Running: 1px live outline on the cell. Failed with no picture: hatch in failed colour at low alpha + error text 11px in failed colour (keep _paint_blank logic, use cell bg not black). Real percent bar 2px live under picture only when view.percent is not None (keep).
Stage mark (group_start): keep, restyle as 11px text on header token chip at cell top-left, no thick rule; and cache group_start (it is O(rows) per painted frame: compute a dict row->stage once in apply_filter / on model reset/rowsInserted and look it up).
Thumbnail fetch size = picture area size (keep ThumbService call).

## 4. Ratings and colour labels (new, small)
- src/gen/models.py Job: add `rating: int = 0` (0-5) and `label: str = ""` (one of "", red, yellow, green, blue, purple). src/projects/store.py: persist both like `review` (read with defaults so old files load). Find every Job serialization (grep `"review": job.review`) and include them.
- SheetView.keyPressEvent on selected rows: 0-5 set rating (0 clears); 6 red, 7 yellow, 8 green, 9 blue toggles label (same key again clears). Emit a new signal `marks_changed(list)` handled in page.py which saves the project the same way review changes are saved and repaints. No credit spend involved.
- Filters: add "rated" (rating>=1) and "labelled" (label != "") filter keys with counts, shown after "Stale" in the tool row.
- Take panel: show the rating stars (clickable QToolButtons, 5) and label swatches (5 small clickable squares + none) under the take's state line.

## 5. Density and Lights (signature)
- J in the sheet (and a tool-row icon button with tooltip "Cell density (J)") cycles density 1 -> 2 -> 0 -> 1. Relayout sizeHint: extra rows add their heights.
- L cycles lights: full -> dim -> out -> full; Esc returns to full. Implement in src/ui/main_window.py as an overlay QWidget child of the central area covering the window, WA_TransparentForMouseEvents, painting black at alpha 0 / 0.70 / 0.92 everywhere EXCEPT the sheet viewport rect (QRegion subtract). Inside the sheet, when lights != full, non-selected cells get the same black alpha painted over them, so only the selected take stays lit. Fade between levels 160 ms OutCubic with QVariantAnimation when theme.motion_enabled(), instant otherwise. Overlay follows resizes. Also offer in Ctrl+K palette as "Lights: dim / out / full" and "Cell density" commands (main_window palette has a command list; add there).
- Shortcut hints: tooltips name keys: Approve (P), Reject (X), Retry (R), Edit (E), Rating 0-5, Labels 6-9, Density (J), Lights (L).

## 6. Inspector (take_panel.py and the Inspector container)
- Each section ("Take", "Prompt", "Why it failed", "This shot") gets a 26px header bar (header token, 11px semibold text_muted sentence case, chevron icon at right) that collapses/expands its body (QToolButton checkable). Remember collapsed state per section in-memory.
- Label/value rows: labels right-aligned in a fixed 112px column, text_muted 11px; values 12px. Action buttons (Approve, Reject, Retry, Edit, View, Open file) as a compact row of flat secondary buttons 26px; Approve keeps accent only when enabled... no: Approve is secondary; the accent shows only on the flag glyph and Start.

## 7. Rail (sidebar.py)
Rail uses sidebar token, items 30px, 12px text, icons 16px rail_muted; active item = rail_selected fill + rail_text, no accent, no bar. Project selector and section gaps as today. Width 200.

## 8. Tests
Keep `python -m pytest` green (except known test_stitch hang). Update tests that pinned old colours/ring; add small tests: rating/label keys set fields and persist round-trip through store; density cycle changes sizeHint; lights cycle levels; group_start cache returns same as old algorithm.
Report: files changed, tests run with counts, anything skipped.
