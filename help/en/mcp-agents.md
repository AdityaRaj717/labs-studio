# Use the google-flow MCP from your own agent

Labs Studio drives Google Flow through an **MCP server** (Model Context Protocol) that ships with the app in the `mcp\google-flow` folder. Any MCP client, such as Claude Code, Claude Desktop, Cursor or Codex, can start the same server and use Flow through tools like `flow_generate_image`, in the same signed-in Chrome window.

Read [Terms of service and your account](terms-and-risks.md) first. An agent can generate much faster than a person, and the risk is to your own Google account.

## What you need

1. **Node.js 18 or newer** on PATH. Check in cmd.exe:

   ```bat
   node --version
   ```

2. The server's packages, installed once. In cmd.exe, go to the `mcp\google-flow` folder inside your Labs Studio folder and run:

   ```bat
   npm ci
   ```

3. A Chrome window signed in to Flow. The easiest way is the app's own: [Signing in to Google Flow](google-flow-sign-in.md). The server attaches to whatever Chrome answers on the debugging port (9333). If nothing does, it starts Chrome itself with the profile folder you give it.

In the examples below, replace:

- `C:\LabsStudio` with your Labs Studio folder;
- the profile folder with the one in **Settings → Web Sessions → Profile folder**, so the agent uses the same sign-in as the app;
- the data folder with the app's own: `D:\glabs_web\flow-mcp` by default (the folder called `flow-mcp` next to the diagnostics folder set in Web Sessions). Keep `FLOW_DATA_DIR` exactly the same in every client; see below.

The server reads these environment variables:

| Variable | Meaning |
|---|---|
| `FLOW_CDP_PORT` | Chrome's debugging port. Use the same one as the app (9333) |
| `FLOW_CHROME_PROFILE_DIR` | Chrome profile folder, used when the server has to start Chrome itself |
| `FLOW_CHROME_PATH` | Path to `chrome.exe`, if it isn't in the usual place |
| `FLOW_DATA_DIR` | Where logs, downloads, screenshots and the server's project list go |
| `FLOW_MCP_CONFIG` | Another config file instead of `config\flow.config.json` |

> **Share one engine, do not start another.** Labs Studio and every agent talk to one local engine that owns Chrome, the queue and the files. They find it through `engine.json` in `FLOW_DATA_DIR`. If your agent uses the same `FLOW_DATA_DIR` as the app (`D:\glabs_web\flow-mcp`, or wherever your app keeps it), it joins the app's engine: the app shows what the agent is doing, the daily cap and credit ledger are shared, and jobs queue instead of colliding. A different folder means a second engine fighting for the same Chrome tab, so don't.

The server needs no API key for Flow. Never paste keys into these config files.

## Claude Code

Add the server for your user account (all projects) from cmd.exe. Everything after `--` is the command that starts the server:

```bat
claude mcp add google-flow --scope user --env FLOW_CDP_PORT=9333 --env FLOW_CHROME_PROFILE_DIR=C:\LabsStudio\browser-profile --env FLOW_DATA_DIR=C:\LabsStudio\flow-mcp-data -- node C:\LabsStudio\mcp\google-flow\src\index.js
```

Leave out `--scope user` to add it only for the project you're in. Check that it connected:

```bat
claude mcp get google-flow
```

To share it with a team, put the same entry in a `.mcp.json` file at the project root, in the `mcpServers` format shown under Claude Desktop.

Docs: [Claude Code MCP](https://code.claude.com/docs/en/mcp).

## Claude Desktop

1. Open Claude Desktop's **Settings → Developer** and press **Edit Config**. That opens `%APPDATA%\Claude\claude_desktop_config.json`.
2. Add the server under `mcpServers`. Use full paths. In JSON, write `\\` for each backslash, or use forward slashes:

   ```json
   {
     "mcpServers": {
       "google-flow": {
         "command": "node",
         "args": ["C:/LabsStudio/mcp/google-flow/src/index.js"],
         "env": {
           "FLOW_CDP_PORT": "9333",
           "FLOW_CHROME_PROFILE_DIR": "C:/LabsStudio/browser-profile",
           "FLOW_DATA_DIR": "D:/glabs_web/flow-mcp"
         }
       }
     }
   }
   ```

3. Quit Claude Desktop completely (also from the system tray) and start it again.

If the server doesn't show up, its log is in `%APPDATA%\Claude\logs\` (`mcp*.log`).

Docs: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

## Cursor

Put the server in `%USERPROFILE%\.cursor\mcp.json` to have it in every project, or in `.cursor\mcp.json` inside one project:

```json
{
  "mcpServers": {
    "google-flow": {
      "type": "stdio",
      "command": "node",
      "args": ["C:/LabsStudio/mcp/google-flow/src/index.js"],
      "env": {
        "FLOW_CDP_PORT": "9333",
        "FLOW_CHROME_PROFILE_DIR": "C:/LabsStudio/browser-profile",
        "FLOW_DATA_DIR": "D:/glabs_web/flow-mcp"
      }
    }
  }
}
```

Then check that it's listed and switched on in Cursor's MCP settings.

Docs: [Cursor MCP](https://cursor.com/docs/context/mcp).

## Codex

Add it from cmd.exe:

```bat
codex mcp add google-flow --env FLOW_CDP_PORT=9333 --env FLOW_CHROME_PROFILE_DIR=C:\LabsStudio\browser-profile --env FLOW_DATA_DIR=C:\LabsStudio\flow-mcp-data -- node C:\LabsStudio\mcp\google-flow\src\index.js
```

That writes an entry to `%USERPROFILE%\.codex\config.toml`. Open that file and raise the tool timeout, because one Flow image takes one to two minutes and Codex stops waiting after 60 seconds by default. The whole entry looks like this (single quotes keep the backslashes as they are):

```toml
[mcp_servers.google-flow]
command = "node"
args = ['C:\LabsStudio\mcp\google-flow\src\index.js']
startup_timeout_sec = 30
tool_timeout_sec = 600

[mcp_servers.google-flow.env]
FLOW_CDP_PORT = "9333"
FLOW_CHROME_PROFILE_DIR = 'C:\LabsStudio\browser-profile'
FLOW_DATA_DIR = 'C:\LabsStudio\flow-mcp-data'
```

A project can have its own `.codex\config.toml` instead (trusted projects only).

Docs: [Codex MCP](https://developers.openai.com/codex/mcp).

## Tools the server offers

| Tool | What it does |
|---|---|
| `flow_connect`, `flow_status`, `flow_account_check`, `flow_disconnect` | Attach to Chrome, check it, see which account is signed in |
| `flow_list_projects`, `flow_open_project`, `flow_rename_project` | List, open (or create) and rename Flow projects |
| `flow_delete_project` | Deletes a Flow project **permanently**. It only acts with `confirm: true`; an agent should ask you first |
| `flow_generate_image` | One prompt → up to 4 images (model, aspect, count, 1K/2K, reference images, `project_url`, `characters`, `scenes`, an output folder) |
| `flow_list_characters`, `flow_create_character`, `flow_import_character` | Flow characters in a project: list, create from an image (free) or a description, copy from another project |
| `flow_list_scenes`, `flow_create_scene` | Places, kept in Flow as characters marked as a place |
| `flow_generate_video`, `flow_download_latest`, `flow_screenshot`, `flow_queue_status` | Older tools. Video hasn't been updated for Flow's current page and may fail. Video generation spends your Flow credits |

Errors come back with an `error_code`. `NOT_LOGGED_IN`, `MANUAL_VERIFICATION_REQUIRED` (a CAPTCHA) and `GOOGLE_LIMIT_REACHED` mean a person has to look at the Chrome window. Don't let an agent retry those in a loop.

A typical agent request: *"Create a Flow project called Episode 2, create a character Mia from C:\refs\mia.png, then make three 16:9 images of Mia in a rainy street."*

## Productions from a prompt folder

A Production turns two Markdown files into References (characters and places), Stills and Animations, with review. Put both in one folder (see `samples\zombie-bunker` in the Labs Studio folder):

- a **moodboard** file, name ends in `moodboard...md`;
- a **prompts** file, name ends in `animation...md`, `still...md` or `image...md` (the first of those that exists is used). If two files match, pass `moodboard_path` and `prompts_path`.

Both must be UTF-8. Lines before the first `##` heading are global: one aspect ratio (16:9, 4:3, 1:1, 3:4 or 9:16) and optionally `Style: ...`.

**Moodboard.** Each Reference is a table row or a `### ID: Name` block with a prompt. Columns or fields: `ID`, `Name`, `Kind` (`character` or `place`), `Prompt`. A Kind comes from the field, else from a `## Characters` or `## Places` heading, else from `(character)` or `(location)` written beside the ID. Ids look like `CH_mia` or `MD_04`.

**Prompts.** Each Shot is a table row or a block with `ID`, `Prompt` and optionally `Refs` (comma list, or `none`), `Start` and `End` frame ids (or `none`), `Duration` (such as `6s`), `Model`, `Resolution`, `Line`. Whether a Shot is a Still or an Animation comes from, in order: the `Type` column (`still`, `image`, `animation`, `video`), a `## Stills` or `## Animations` heading, or the id prefix (`IMG_`, `STILL_`, `SHOT_` for stills; `ANI_`, `ANIM_`, `VID_` for animations). **A free-form plan whose shots have none of these is rejected with "no Type, section or ID prefix", so give every shot a `Kind`/`Type` or a recognisable id.** A row with both `Image prompt` and `Animation prompt` columns becomes a Still `<id>_IMG` plus an Animation `<id>_ANI` that starts from it.

Workflow for an agent:

1. `flow_production_plan` with `folder`. Free; it reads the files and shows the cast, cost estimate and any questions.
2. Read both files, answer the questions (for example mark `MD_04` as a place), and plan again.
3. `flow_production_start` with `plan_id`, `cast_confirmed: true`, `auto_confirm: true` and, if there are Animations, `max_credits`. This spends credits; get the owner's agreement first.
4. Loop `flow_wait` until it reaches `waiting_review`, `needs_action`, `paused`, `cancelled` or `complete`.
5. The owner approves or rejects Takes (in the app, or `flow_production_review`). `flow_production_regenerate` makes a new Take of one Item.

## Recovery

State lives on disk, so most stops are safe to resume. A job that was already submitted to Flow is never run again by itself, because a repeat spends credits again.

| Situation | What to do |
|---|---|
| The engine was killed (crash, closed terminal, reboot) | Start your agent or the app again. The engine restarts from `engine.json` and the journal, and an item already submitted is not spent twice. Then `flow_job_control` `resume` on the `run_id`. If it says the engine is stale, delete nothing: just call any tool and it starts a new one |
| Chrome was closed | The running item fails with "Chrome or the Flow tab closed". Reopen the app's Chrome window, check you are still signed in, then `flow_job_control` `retry_failed`. That attempt may already have been charged |
| Daily cap reached | The queue stops with `DAILY_CAP_REACHED`. Wait for tomorrow, or raise the cap in the app's Web Sessions settings if you are sure, then Retry; the next app job frees the queue. Agents: `flow_job_control` resume |
| Google's own usage limit, a CAPTCHA, or "verify it's you" | A person must act in the Chrome window. Do not let an agent retry in a loop. Then `resume` |
| Quote higher than expected (`quote_drift`) | Flow changed a price. `resume` with `accept_quote: true` only if the new price is fine |
| A cap too small for a retry | Raise it with `flow_job_control` `set_budget`, only if you agree |
| A few items failed | `flow_job_control` `retry_failed` on the `run_id`. Each error has `retryable`, `credits_at_risk` and `next_action`; follow `next_action` |
