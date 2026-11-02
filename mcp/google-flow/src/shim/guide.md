# Google Flow engine: how to work with it

One local engine owns Chrome, the queue and the files. All agents and the app share it, so a job you did not start may be running.

## Workflow

1. `flow_connect`, then `flow_status`. If it reports a sign-in problem, ask the owner to sign in by hand in the Chrome window.
2. `flow_capabilities` lists models, ratios, sizes, limits and costs. Pick values from it.
3. Call `flow_generate_image` without `auto_confirm` for a free dry run. Nothing touches the browser.
4. Call it again with `auto_confirm: true` and an `idempotency_key`. You get `job_id` and `run_id` at once, and the job queues behind any other job.
5. Loop on `flow_wait` (at most 55000 ms per call) until `finished` is true. A `paused` field means the queue is stopped for the owner.
6. Use `flow_job_control` with `pause`, `resume`, `cancel` or `retry_failed`.

## Productions

A folder with a moodboard file and a prompts file becomes References, then Stills, then silent Animations.

1. `flow_production_plan` with `folder`. Free, no browser. The engine parses tables and blocks only; it never interprets prose.
2. Read both files yourself. Answer `analysis_needed` through `overrides`, for example `{references: [{id: "MD_04", kind: "place"}]}` or `split_from` for a row hiding two people, then plan again.
3. `flow_production_start` with `plan_id`, `cast_confirmed: true`, `auto_confirm: true`, and `max_credits` if it has Animations. `cast_confirmed` means you read both files and every Reference is exactly one subject.
4. Loop `flow_wait` on `run_id`. `production` in the reply has the status and `next_action`. It finishes at `waiting_review`, `needs_action`, `paused`, `cancelled` or `complete`.
5. At `waiting_review`, tell the owner. Never approve unless the owner told you to.
6. A stop for quota or verification pauses it, and `flow_job_control` `resume` with `run_id` goes on. A quote above an estimate stops it as `quote_drift`: `resume` with `accept_quote: true` only if that price is acceptable.
7. `flow_production_review` names each Take: `items: [{id: "IMG_01", take: 2}]`, `action: approve` or `reject`. It works with Chrome closed. Your verdicts are recorded as `agent`.
8. `flow_production_regenerate` makes a new Take of one Item: no `prompt` retries, a `prompt` modifies. Pass `expected_take`, so a repeat after a timeout returns the running Take and spends nothing. For an Animation, call with `dry_run: true`, then `auto_confirm: true`. If it no longer fits, `flow_job_control` `set_budget` raises the cap, only if the owner agreed.
9. An approved Item built from an old Take is listed in `stale`. Nothing changes by itself: ask the owner whether to regenerate it.

## Rules

- `submitted` is the credit line. Past it a job is never run again without `retry_failed`, because a retry spends again.
- Never try to get past a CAPTCHA, verification or limit. Tell the owner.
- A failure has `error_code`, `retryable`, `credits_at_risk` and `next_action`. Do what `next_action` says.
- `NOT_IMPLEMENTED` means that tool is not built yet.
- `flow_batch_start` without `auto_confirm` is a free estimate. With it, one run queues; loop `flow_wait` on `run_id`, then `flow_job_control` with `resume` for what was held and `retry_failed` for what failed.
- `flow_delete_project` is permanent. Pass `confirm: true` only after the owner agreed to delete that project.
- While a job runs, tools that need the Flow tab return `JOB_IN_PROGRESS`. `flow_status`, `flow_wait` and `flow_screenshot` still work.
