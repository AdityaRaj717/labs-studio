# Flow UI findings (Task 2 spike, 2026-11-02)

Live on `flow.google.com`, Pro account, project `spike-2026-11-02`. Credits spent: **25 of the 40 cap** (1,050 to 1,025). Masked snapshots are in `mcp/google-flow/test/fixtures/snapshots/`.

## The big one: direct mode replaces the agent

The composer has an **Agent** toggle, visible only while the chat panel is closed. With it off, the composer drives generation directly, with no Flow agent in the middle and no chat turn.

- Closing the panel: `button "Close"` in the session header. Toggle: `button "Agent"`, with `[pressed]` meaning agent on. The state survived a reload.
- `button "Settings trigger"` opens the settings and names the current state, for example `Video · 360p · 4s x1` or `🍌 Nano Banana 2.1 x1`.
- Inside, unnamed radiogroups hold real radios, found by radio name:
  - Kind: `Image`, `Video`.
  - Video mode: `Frames`, `Ingredients`.
  - Ratio: image `16:9 4:3 1:1 3:4 9:16`; video `16:9 9:16`.
  - `button "Select model family"` opens a menu of `menuitem`s.
  - Omni only: resolution `360p`, `720p` and duration `4s 6s 8s 10s`.
  - Count `x1`-`x4`.
- **Live cost:** `Generating will use` plus `link "N credits"`. Read it, compare it, then click.
- Closing the settings: click `Settings trigger` again. Its overlay has no backdrop class to rely on.
- Frames mode composer has `Start` and `End` chips (`button.empty-chip`, text only) and `Swap first and last frames`. A chip opens the picker.

### Costs read from the live control at x1

| Model | Duration | Resolution | Credits |
|---|---|---|---|
| Omni 1.1 Flash | 4 / 6 / 8 / 10s | 720p | 7 / 10 / 12 / 15 |
| Omni 1.1 Flash | 4s | 360p | 4 (others per help: 5, 6, 7) |
| Veo 3.1 Lite | no control | no control | 10 |
| Veo 3.1 Fast | no control | no control | 20 |
| Veo 3.1 Quality | no control | no control | 100 |
| Any image model | | | 0 |

x2 multiplies (8s 720p x2 showed 24). Every balance change matched the quote exactly and showed immediately: 4, 10, 7, 4.

**Veo has no duration or resolution control on Pro.** It produced 8s at 720p. The agent also refused 4s: "does not support 4-second video generation on the Pro/Plus tier". The help page's 4 and 6s Veo claim doesn't hold on this plan. Veo Quality appears with Ingredients in the UI at 100, but the help page excludes it; validation keeps rejecting that mix since it hasn't been tried.

## Progress and completion (all modes)

The source of truth is the **tile**, not the chat.

- Tile: `flow-grid-tile-container[role=group]`, `aria-label` is first the prompt, then an auto-generated title. Titles repeat across tiles, so they aren't identity. New tiles appear at the top.
- While running: `text: <n>% <prompt>`. This is **Flow's own percentage**, so progress has `source: flow`. It isn't linear: images climbed to 77 then flipped; videos went 10 to 100 and 31 to done.
- Finished image: `img "Tile displaying a user's image"` with `data-media-id` on the `img`. Finished video: `img "Generated video thumbnail"` plus text like `360p`, in `flow-video-tile`. No media id on a resting video tile.
- Timing: images about 40s; Omni 360p 4s about 30s; Veo Lite 8s about 70s.
- In agent mode a video's chat turn ends ("scheduled and is waiting in the queue") while the tile is at 3%. Chat turns can't signal done.
- Failed or blocked tile: **not observed**. One prompt expected to be refused generated normally, and I didn't push further. The code must treat a tile that leaves the running state without a finished media element as failed, and capture its text. Toasts seen use plain text plus `button "Dismiss"`.

## Asset info and identity

- Hover a tile, then its title button (same name as the tile), toggles a popover: `heading`, prompt text, and for example `Created Nov 2, 2026 Omni 1.1 Flash 16:9 4s Resolution: 360p`. Model, ratio, duration and resolution are all readable, so model verification works. Click the same button again to close.
- Clicking the tile's media element opens `/project/<id>/edit/<media-uuid>`, which gives the full id. `button "Done editing scene"` leaves.
- Downloaded filenames end in the first 8 hex of the id: `Paper_boat_turns_in_water_fccf7a8b.mp4`.

## Downloads

Tile hover, `button "More options"`, `menuitem "Download"`, then a size menu. Scope `More options` to the tile: the page has its own with `Download project`.

| Kind | Items | Result |
|---|---|---|
| Image | `1K Original size`, `2K Upscaled`, `4K Upscaled [disabled]` | **JPEG**, 1376x768 (2.6s) and 2752x1536 (15s) for 16:9 |
| Omni 360p | `270p Animated GIF`, `360p Original size`, `720p Upscaled` | h264 + aac, 640x360, 4.03s |
| 720p videos | `720p Original size`, `1080p Upscaled`, `4K Upscaled [disabled]` | 1280x720; 4.03s and 7.93s |

Playwright's `download` event works over CDP. Use the suggested filename for the extension. 16:9 images are 1.79:1, so ratio checks need about 3% tolerance. Video duration checks need about 0.5s tolerance. A toast `Your video has been downloaded!` stays until dismissed.

## Return silent videos does not silence

With the page setting on, Omni 720p came back with an aac stream at max -19.9 dB, and Omni 360p at -31 dB. Normal clips measured -18 and -13.6 dB. The toggle can't be trusted, so `silent: true` strips the audio locally with FFmpeg and keeps the original. The spike left the toggle off.

## Other surfaces

- **Balance:** `button "Account details"` opens `dialog "Account settings"` with `link "1,025 Google Flow credits"` and `Resets Nov 9 at 6:18 PM`. Close with `button "Close account panel"`; Escape doesn't. The ledger can use the real balance.
- **Page settings:** first `button "Settings"` opens a menu with View mode, Grid size, and switches `Sound on hover`, `Return silent videos`, `Show tile details`, `Clear prompt on submit`. Close with the `.cdk-overlay-backdrop` element.
- **Picker:** `button "Add ingredients to the prompt box"`; `combobox "Select project"` allows other projects; tabs All, Images, Videos, Voices, Characters, Avatars, Uploads; `listbox "Asset list"` with `option`s; `button "Add to prompt"`; `button "Upload media"` raises a **file chooser**, with no static input. Upload state: option `Uploading <file> Image` becomes `<file> Image` in about 6s.
- **Attached ingredient:** not in the accessibility tree by name; `flow-ingredient-chip button[aria-label=Ingredient]`, `aria-busy` is false when ready.
- **Delete project:** `dialog "Are you sure you want to delete this project?"`, confirm `button "Delete project"`, `Cancel`.
- **Home:** 14 projects all present with no lazy loading seen. Cards are `link "Open project"`, then name text, `Edit project title`, `Delete project`. Promo banner rotates.
- **Rename project:** `textbox "Editable text"` in the header, select all, type, Enter.
- **Project sidebar** gains `Images`, `Videos`, `Uploads` only once such assets exist. Characters and Scenes are always there.
- **Characters:** Add media, `Create character`, opens `/project/<id>/character` with sample archetypes, `textbox "Describe your character…"`, `button "Upload"`, `button "Add from project"`. With no characters, the sidebar's `Characters` opens this same page. Save flow not run in the spike.
- **Scenes:** `New scene` immediately creates `/scene/<uuid>`. Not a harmless click. Untitled Scene left in the spike project.
- **Editor:** `button "Add clip"` gives `menuitem "Add clip"` and `menuitem "Extend (Veo 3.1 - Lite)"`. **Extend is disabled on Omni clips**, enabled on Veo clips. Extend mode: `textbox "What happens next?"`, `button "Exit extend mode"`, and an 8s placeholder. Omni edit: `textbox "Describe how to edit this video…"` with `Omni 1.1 Flash`. Other controls: `Save frame`, `Download media`, `Move to trash`. Neither Extend nor edit was run.
- **Tools:** `/tools` shows only `My creations` and `Create New`. **Grid Architect isn't reachable, which settles C6: removed.**
- **Pop-ups:** a promo card with `Got it` can cover the composer; dismiss it if present.
- **Network:** generation uses Flow's own `batchexecute`, a reCAPTCHA worker runs on the page. We stay on the page only.
- **Screenshots:** `page.screenshot` once hung 30s waiting for fonts, and CDP capture hung once. Both need a hard timeout, and failure to capture must never fail a job.

## Agent mode, for the record

Confirm Always gives a plan plus `costing N credits` with `radiogroup "Permission options"` (`Approve`, `Always approve`, `Reject`). A question comes back as plain paragraphs and lists with no radios. Duration and resolution are taken from prompt text. It works, but direct mode is more exact, faster, and doesn't use the agent's daily query limit.

# Y0 reference spike (2026-11-02)

Live in project `y0-2026-11-02` (065acc3b-852c-4cf2-84c6-80359d0543bd). Credits: 8, balance 1,025 to 1,017. Images used quota only. Result files are in `tools/flow_spike/out/y0/` (git-ignored). **The primary from R4 stands: `referenceMode: ingredient`.**

## Answers

1. **Sheet as ingredient:** identity held in both Shots (face, eyebrow scar, jacket, gloves), and the place carried over. No grid layout leaked. Judged by viewing `y0-ing-img01.jpg` and `y0-ing-img04.jpg`. IMG_04 was reduced to one person, as only one sheet was made.
2. **Flow Character:** works in direct mode. Upload goes straight to `/project/<id>/character/<uuid>` with the image set; set `Character name`, then `Done` returns to the project. Tab `Characters` in the picker lists it; clicking its option attaches at once as a chip with `img "Character ingredient image"`, with no `Add to prompt` step. Result `y0-char-img01.jpg` is the same man. Fallback remains valid.
3. **Ingredient limit:** image accepted 16 chips with no refusal, so the limit is **at least 16**. Video: **unknown**, `maxIngredients.video` is null. The attempt to add more failed on a click timeout for reasons not diagnosed, not on a refusal; one chip is proven. Y3 must count ready chips before Start and fail with no spend on a mismatch; Y8 tests multiple chips on video.
4. **Video:** Omni 360p 4s at 4 credits, both modes, 27s each, 640x360, 4.0s, one audio stream each. Frames with an uploaded Still: first frame matches it. Ingredients with the sheet: same outfit, face less distinct at 360p.

## Corrections for the pipeline

- **Model menu labels have an emoji prefix** (`🍌 Nano Banana 2.1`). Exact names failed live and passed on fake Flow; contract now uses a suffix regex. Fake Flow should copy this.
- **Saved Characters are grid tiles.** `flow-grid-tile-container` with `img "Character thumbnail"`, and it sat at index 1 among results. "New tiles at the top" must ignore these and match on finished media.
- **Chips clear** after a job and on reload. Ingredient chips from the previous Shot don't carry over. Y3 still asserts the count.
- **Picker search finds an upload by exact filename on a later job.**
- **Clicking a picker option can attach immediately**, removing `Add to prompt` from the DOM. Treat that button as optional, and confirm by chip count.
- A `Download` once timed out at 120s right after picking a Character, and worked after closing overlays. Cause not established. Download should close overlays first and bound its wait.
- Tile menu items: `Reuse prompt`, `Animate`, `Add to prompt`, `Download`, `Copy`, `Rename`, `Share`, `Set project cover`, `Flag output`, `Move to trash`, `Favorite`. Page-level `Create body`, `Portrait`, `Select a voice` appear on the character page; unused.
- Failed tile still not observed.
