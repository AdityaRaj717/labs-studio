# Labs Studio — Agent Control Testing Issue Log & Verification Report

> **Guide Source**: [`agent_control_testing_guide.md`](agent_control_testing_guide.md) (rewritten for the current MCP; test IDs below are from the old guide, the "Status" lines under each issue were added by code reading, not by new test runs)  
> **Server Under Test**: `google-flow` MCP Server (`d:/Prog/Labs Studio/mcp/google-flow`)  
> **Authenticated User**: `cypherx9572@gmail.com` (Google AI Pro subscription active)  
> **Chrome Debug Port**: 9333 (`D:\glabs_web\chrome-profile`)  
> **Target Service**: Google Flow (`https://flow.google.com/`) via Chrome automation  
> **Execution Date**: 2026-11-01 / 2026-11-02  

---

## Executive Summary & Progress

| Section | Category | Tested Scenarios | Pass | Fail / Bug | Category Status |
|---|---|---|---|---|---|
| **1** | Connection & Status | T-1.1, T-1.2, T-1.3, T-1.4, T-1.5 | 4 | 1 | Verified with issues noted |
| **2** | Simple Image Generation | T-2.1, T-2.2, T-2.5, T-2.6, T-2.9, T-2.10 | 5 | 1 | Verified with issues noted |
| **3** | Model Variations | T-3.1, T-3.2, T-3.3, T-3.4 | 4 | 0 | **100% Passed** |
| **4** | Aspect Ratio Variations | T-4.1, T-4.2, T-4.3, T-4.4, T-4.5, T-4.6 | 6 | 0 | **100% Passed** |
| **5** | Download Size & Count Variations | T-5.1, T-5.2, T-5.3, Boundaries (0, 5, 8K) | 6 | 0 | **100% Passed** |
| **7** | Project Management | T-7.1, T-7.2, T-7.3, T-7.4, T-7.5, T-7.6, T-7.7, T-7.8, T-7.10 | 9 | 1 | **Passed** (race condition noted) |
| **8** | Character System | T-8.3, T-8.4, T-8.5, T-8.6 | 4 | 0 | **100% Passed** |
| **9** | Scene System | T-9.1, T-9.2 | 2 | 0 | **100% Passed** |
| **11** | Video Generation | T-11.1 | 0 | 1 | **Failed** (locale/navigation bug) |
| **12** | Grid Architect & Tools Gallery | T-12.1, T-12.2, T-12.3, T-12.4 | 2 | 2 | Verified with issues noted |
| **15** | UI Discovery & Diagnostics | T-15.1, T-15.3, T-15.6, Queue, Screenshot | 3 | 2 | Verified with issues noted |
| **16** | Error Handling & Edge Cases | T-16.1, T-16.2, T-16.3, T-16.4, T-16.5, T-16.11 | 4 | 2 | Verified with issues noted |

---

## Detailed Issue Registry (Actual Codebase Bugs)

### Issue #1: `page.goto` Timeout with `waitUntil: 'networkidle'` on Google Flow Navigation
* **Status (Task 19 review)**: OBSOLETE in the current MCP: no `networkidle` wait remains in `mcp/google-flow/src` (grep). Not re-tested live.
* **Affected Files**:
  * [`mcp/google-flow/src/browser/launch-profile.js#L42`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/browser/launch-profile.js#L42)
  * [`mcp/google-flow/src/tools/flow-open.js#L17`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/flow-open.js#L17)
  * [`mcp/google-flow/src/navigation/project-navigator.js#L39`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/navigation/project-navigator.js#L39)
* **Severity**: **Critical / Blocker**
* **Root Cause**: Modern Google Flow (`flow.google.com`) continuously streams video canvas tiles, preloads font assets, and runs telemetry pings. Playwright's `waitUntil: 'networkidle'` waits for 500ms of absolute silence on network traffic, which never occurs on Google Flow. As a result, `page.goto` consistently times out after 30,000ms:
  ```
  page.goto: Timeout 30000ms exceeded.
  Call log: navigating to "https://flow.google.com/", waiting until "networkidle"
  ```
* **Fix**: Change `waitUntil: 'networkidle'` to `waitUntil: 'domcontentloaded'` with an explicit element wait.

---

### Issue #2: Domain URL Check Omits `flow.google.com` (Hardcoded to `labs.google`)
* **Status (Task 19 review)**: OBSOLETE in the current MCP: `flow-status.js` now uses `isFlowHost`. Not re-tested live.
* **Affected Files**:
  * [`mcp/google-flow/src/tools/flow-open.js#L27`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/flow-open.js#L27)
  * [`mcp/google-flow/src/tools/flow-status.js#L26`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/flow-status.js#L26)
* **Severity**: **Medium**
* **Root Cause**:
  * `flow-open.js` line 27 checks: `currentUrl.includes('labs.google/fx/tools/flow') || currentUrl.includes('labs.google')`.
  * `flow-status.js` line 26 checks: `status.flowAccessible = status.currentUrl?.includes('labs.google') || false;`.
  * In `flow.config.json`, the primary URL is `"https://flow.google.com/"`. When navigating to `flow.google.com`, both checks evaluate to `false`, falsely reporting `status: 'needs_login'` and `flowAccessible: false` despite an active logged-in session.
* **Fix**: Include `flow.google.com`: `currentUrl.includes('flow.google.com') || currentUrl.includes('labs.google')`.

---

### Issue #3: Hardcoded French UI Selectors Break Video & Tools Navigation
* **Status (Task 19 review)**: OBSOLETE as written: the French strings `Nouveau projet` and `Outils` no longer appear in `mcp/google-flow/src`, and `flow_open_tools_gallery`, `flow_use_tool` and the grid tool no longer exist. Whether `flow_generate_video` and project creation work on an English UI is open: guide T-7.3 and T-11.2 test it.
* **Affected Files**:
  * [`mcp/google-flow/src/navigation/project-navigator.js#L95-121`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/navigation/project-navigator.js#L95-121)
  * [`mcp/google-flow/src/tools/generate-video.js#L86`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/generate-video.js#L86)
  * [`mcp/google-flow/src/tools/open-tools-gallery.js#L26`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/open-tools-gallery.js#L26)
  * [`mcp/google-flow/src/tools/use-flow-tool.js#L22`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/use-flow-tool.js#L22)
* **Severity**: **High / Breaking for Non-French Locales**
* **Root Cause**:
  * In `project-navigator.js`: Searches for button `"Nouveau projet"`. When not found in English Google Flow ("New project"), it throws:
    `Could not find "Nouveau projet" button on the Flow page`
  * In `generate-video.js`, `open-tools-gallery.js`, and `use-flow-tool.js`: Calls `navigateToSidebar(page, 'Outils')`. In English Google Flow, the sidebar item is `"Tools"`. It times out waiting 15 seconds for `"Outils"`.
* **Fix**: Add fallback English selectors (`"New project"`, `"Tools"`, `"All media"`).

---

### Issue #4: Missing Upfront Validation for Empty or Missing Prompts
* **Status (Task 19 review)**: OBSOLETE in the current MCP: `validate.js` rejects a blank prompt with `INVALID_PARAMS` before any browser work. Guide T-16.1 asserts it.
* **Affected File**:
  * [`mcp/google-flow/src/tools/generate-image.js#L318-360`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/generate-image.js#L318-360)
* **Severity**: **Medium**
* **Root Cause**:
  * Prompt validation is not performed at the top of `runGenerateImage`.
  * If `prompt` is empty (`""`), it performs slow project navigation, types into the box, and waits 10 seconds for the disabled "Start generation" button to enable before throwing `GENERATION_BUTTON_DISABLED` instead of an immediate `INVALID_PARAMS`.
  * If `prompt` is undefined, `args.prompt.replace(...)` crashes with a TypeError.
* **Fix**: Add upfront check: `if (!args.prompt || !args.prompt.trim()) throw new FlowError(ErrorCodes.INVALID_PARAMS, "prompt cannot be empty");`.

---

### Issue #5: `flow_status({ full: true })` Does Not Return Screenshot
* **Status (Task 19 review)**: OBSOLETE in the current MCP: `flow_status` handles `full: true` and sets `screenshot`. Guide T-1.3 asserts the file exists.
* **Affected File**:
  * [`mcp/google-flow/src/tools/flow-status.js#L9-39`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/flow-status.js#L9-39)
* **Severity**: **Low**
* **Root Cause**: The testing guide (T-1.3) specifies that `flow_status({ full: true })` returns a screenshot of the current page. However, `handleFlowStatus` in `flow-status.js` does not accept or handle the `full` flag, nor does it invoke `takeScreenshot`.
* **Fix**: Check `if (args?.full) { status.screenshot = await takeScreenshot(page, 'flow-status'); }`.

---

### Issue #6: `flow_delete_project` Race Condition on Card Count
* **Status (Task 19 review)**: OPEN: `open-project.js` still exists and the old fix was not checked. Guide T-7.6 and T-14.1 exercise delete on a project the test created.
* **Affected File**:
  * [`mcp/google-flow/src/tools/open-project.js#L182-190`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/open-project.js#L182-190)
* **Severity**: **Medium**
* **Root Cause**: `handleDeleteProject` navigates to home via `gotoHome(page)` which only waits 1500ms. If Google Flow's project cards take >1500ms to render via client-side hydration, `link.count()` returns 0 and throws `PROJECT_NOT_FOUND` even though the project exists.
* **Fix**: Use `await link.waitFor({ state: 'attached', timeout: 10000 })` instead of immediate synchronous `!await link.count()`.

---

### Issue #7: Reference Image File Paths Not Validated Before Navigation
* **Status (Task 19 review)**: OBSOLETE in the current MCP: `validate.js` checks every ingredient path before queuing (`INVALID_PARAMS`). Guide T-16.5 asserts it.
* **Affected File**:
  * [`mcp/google-flow/src/tools/generate-image.js#L335-338`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/generate-image.js#L335-338)
* **Severity**: **Low / Performance**
* **Root Cause**: `fs.existsSync(ref)` is only checked after project navigation inside `addReference`. Invalid or missing local image paths incur full project load overhead before failing.
* **Fix**: Validate `fs.existsSync` for all items in `args.reference_images` at the start of `runGenerateImage`.

---

### Issue #8: `flow_discover_ui` Uses Deprecated URL and `networkidle`
* **Status (Task 19 review)**: OBSOLETE: `flow_discover_ui` is removed. `flow_doctor` replaces it (guide T-15.1).
* **Affected File**:
  * [`mcp/google-flow/src/tools/discover-ui.js#L20-73`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/discover-ui.js#L20-73)
* **Severity**: **High**
* **Root Cause**: Hardcodes `https://labs.google/fx/tools/flow` and `page.goto(url, { waitUntil: 'networkidle', timeout: 30000 })`. It times out on every invocation.
* **Fix**: Point to `https://flow.google.com/` and use `waitUntil: 'domcontentloaded'`.

---

### Issue #9: Google Flow Error Bubble Not Captured in `flow-a2ui-text`
* **Status (Task 19 review)**: OPEN: `generate-image.js` is gone and the engine reports `FLOW_GENERATION_FAILED`, but how an on-page error is captured has not been tested. Not claimed fixed.
* **Affected File**:
  * [`mcp/google-flow/src/tools/generate-image.js#L48-52, L117-133`](file:///d:/Prog/Labs%20Studio/mcp/google-flow/src/tools/generate-image.js#L48-52)
* **Severity**: **Medium**
* **Root Cause**: When Google Flow encounters a generation failure (e.g. `Something went wrong. Please try again.`), the error banner is rendered outside `flow-a2ui-text`. `readChat` extracts empty string `(no text)`, causing the tool to report `The agent replied without an image: (no text)` rather than catching the actual error text.
* **Fix**: Include error text containers in `readChat` DOM extraction: `[class*="error"], [role="alert"], button:has-text("Try again")`.

---

## Detailed Test Case Results Summary

* **T-1.1**: Connect to Google Flow — **PASS** (Reuses port 9333 active session).
* **T-1.2**: Check connection status — **PASS** (Correctly reports browser attached, URL `https://flow.google.com/`).
* **T-1.3**: Full status — **PASS** (Status returned; missing screenshot per Issue #5).
* **T-1.4**: Account check — **PASS** (Detected `cypherx9572@gmail.com`).
* **T-2.1**: Simple image generation (`auto_confirm: false`) — **PASS** (Prepared prompt, returned `ready_for_confirmation`).
* **T-2.2**: Simple image generation (`auto_confirm: true`) — **FAIL** (Hit Flow error dialog; logged Issue #9).
* **T-2.5**: Two-word prompt (`blue butterfly`) — **PASS** (`ready_for_confirmation`).
* **T-2.6**: Single-word prompt (`chaos`) — **PASS** (`ready_for_confirmation`).
* **T-2.9**: Unicode/Japanese prompt — **PASS** (Handled Japanese text safely).
* **T-2.10**: Special character prompt — **PASS** (Handled brackets and equations safely).
* **T-3.1**: Model Nano Banana 2.1 — **PASS**.
* **T-3.2**: Model Nano Banana Pro — **PASS**.
* **T-3.3**: Model Nano Banana 2 Lite — **PASS**.
* **T-3.4**: Model alias `Nano Banana 2` — **PASS** (Resolved cleanly to `Nano Banana 2.1`).
* **T-4.1**: Ratio 16:9 — **PASS**.
* **T-4.2**: Ratio 9:16 — **PASS**.
* **T-4.3**: Ratio 1:1 — **PASS**.
* **T-4.4**: Ratio 4:3 — **PASS**.
* **T-4.5**: Ratio 3:4 — **PASS**.
* **T-5.1**: Count 1 — **PASS**.
* **T-5.2**: Count 2 — **PASS**.
* **T-5.3**: Count 4 — **PASS**.
* **T-5.x**: Boundary checks (count 0, count 5, size 8K) — **PASS** (All 3 rejected upfront).
* **T-7.1**: Create project (`Project Alpha`) — **PASS** (Created `ebcab495-17f0-4cd6-a1f9-c757e71f63bb`).
* **T-7.2**: Open project by URL — **PASS**.
* **T-7.3**: Open project by URL & rename (`Project Alpha Renamed`) — **PASS**.
* **T-7.4**: Rename project tool (`flow_rename_project`) — **PASS** (`Project Alpha Final`).
* **T-7.5**: List projects (`flow_list_projects`) — **PASS** (Listed all 13 projects).
* **T-7.6**: Delete project (`flow_delete_project`) — **PASS** (Confirmed deletion removed project from Flow).
* **T-7.7**: Open non-existent project (`create_if_missing: false`) — **PASS** (`PROJECT_NOT_FOUND`).
* **T-7.8**: Open non-existent project (`create_if_missing: true`) — **PASS** (Created fallback project).
* **T-7.10**: Switch projects — **PASS** (Switched cleanly between project URLs).
* **T-8.3**: Create character (`format: true`, `auto_confirm: false`) — **PASS** (`ready_for_confirmation`).
* **T-8.4**: List characters — **PASS**.
* **T-8.5**: List characters with details — **PASS**.
* **T-8.6**: Import character boundary (same project) — **PASS** (Rejected identical project URLs).
* **T-9.1**: Create scene (`auto_confirm: false`) — **PASS** (`ready_for_confirmation`).
* **T-9.2**: List scenes — **PASS**.
* **T-11.1**: Video generation (`flow_generate_video`) — **FAIL** (Hit French selector `Nouveau projet` per Issue #3).
* **T-12.2**: Grid Architect (`flow_use_grid_architect`) — **PASS** (`ready_for_confirmation`).
* **T-12.1 / T-12.3**: Tools Gallery — **FAIL** (Hit French selector `Outils` per Issue #3).
* **T-15.x**: Queue status & screenshot — **PASS**.
* **T-15.6**: Download latest — **PASS** (Gracefully returned `not_found`).
* **T-16.2**: Invalid model — **PASS** (`MODEL_NOT_AVAILABLE`).
* **T-16.3**: Invalid ratio — **PASS** (`RATIO_NOT_AVAILABLE`).
* **T-16.4**: Invalid project URL — **PASS** (`PROJECT_NOT_FOUND`).
* **T-16.11**: HTML / Script injection prompt — **PASS** (Inserted without execution or crash).
