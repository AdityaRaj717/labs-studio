# Google Flow engine: how to work with it

One local engine owns Chrome, the queue and the files. All agents and the app share it, so a job you did not start may be running.

## Workflow

1. `flow_connect`, then `flow_status`. If it reports a sign-in problem, ask the owner to sign in by hand in the Chrome window.
2. `flow_capabilities` lists models, ratios, sizes, limits and costs. Pick values from it.
3. Call `flow_generate_image` without `auto_confirm` for a free dry run. Nothing touches the browser.
4. Call it again with `auto_confirm: true` and an `idempotency_key`. You get `job_id` and `run_id` at once, and the job queues behind any other job.
5. Loop on `flow_wait` (at most 55000 ms per call) until `finished` is true. A `paused` field means the queue is stopped for the owner.
6. Use `flow_job_control` with `pause`, `resume`, `cancel` or `retry_failed`.

## Rules

- `submitted` is the credit line. Past it a job is never run again without `retry_failed`, because a retry spends again.
- Never try to get past a CAPTCHA, verification or limit. Tell the owner.
- A failure has `error_code`, `retryable`, `credits_at_risk` and `next_action`. Do what `next_action` says.
- `NOT_IMPLEMENTED` means that tool is not built yet.
- `flow_delete_project` is permanent. Pass `confirm: true` only after the owner agreed to delete that project.
- While a job runs, tools that need the Flow tab return `JOB_IN_PROGRESS`. `flow_status`, `flow_wait` and `flow_screenshot` still work.
