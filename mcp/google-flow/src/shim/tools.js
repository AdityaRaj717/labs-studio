// Spec 6.4.
const OBJECT = (properties = {}, required) => ({ type: 'object', properties, ...(required ? { required } : {}) });
const hints = (readOnlyHint, destructiveHint, idempotentHint, openWorldHint = true) => ({ readOnlyHint, destructiveHint, idempotentHint, openWorldHint });
const READ = hints(true, false, true);
const LOCAL_READ = hints(true, false, true, false);
const WRITE = hints(false, false, false);
const SAME = hints(false, false, true);
const DELETE = hints(false, true, true);

const tool = (name, description, annotations, inputSchema = OBJECT()) => ({ name, description, annotations, inputSchema });

const SPEND = {
  auto_confirm: { type: 'boolean', default: false, description: 'CREDITS. false: free dry run, no browser. true: queue the job.' },
  max_credits: { type: 'number', default: 30, description: 'Refuse if the estimate is above this.' },
  idempotency_key: { type: 'string', description: 'A repeat with this key returns the first job and spends nothing.' },
  output_root: { type: 'string', description: 'Folder for the run. Default %APPDATA%\\LabsStudio\\outputs.' },
  project_url: { type: 'string', description: 'Flow project to generate in.' },
  project_name: { type: 'string', description: 'Project title, reused or created when project_url is absent.' },
};
const INGREDIENTS = {
  type: 'array',
  description: 'File paths, or objects naming a file, character, scene or project.',
  items: { oneOf: [{ type: 'string' }, { type: 'object' }] },
};
const TARGET = { job_id: { type: 'string' }, run_id: { type: 'string' } };
const STITCH_ID = { type: 'string', description: 'From stitch_video.' };
const CHARACTER = OBJECT({
  project_url: { type: 'string' },
  name: { type: 'string' },
  prompt: { type: 'string', description: 'Without images Flow generates a portrait, which spends: needs auto_confirm.' },
  images: { type: 'array', items: { type: 'string' } },
  info: { type: 'string' },
  auto_confirm: { type: 'boolean', default: false },
  from_project_title: { type: 'string' },
}, ['project_url', 'name']);

export const TOOLS = [
  tool('flow_connect', 'Launch or attach to the Flow Chrome (dedicated profile), open Flow and check the account.', SAME, OBJECT({
    open_flow: { type: 'boolean', default: true, description: 'Also open the Flow home page.' },
  })),
  tool('flow_disconnect', 'Detach from Chrome. Chrome and its tabs stay open.', SAME),
  tool('flow_status', 'Browser, account, Flow page, active job, today\'s quotas, month\'s credits and balance. Skips the page while a job runs.', READ, OBJECT({
    full: { type: 'boolean', default: false, description: 'Add a screenshot path.' },
  })),
  tool('flow_doctor', 'Read-only check of the Flow page against the UI contract. Spends nothing.', READ),
  tool('flow_capabilities', 'Models, ratios, durations, sizes, costs, limits and the date they were verified.', LOCAL_READ),

  tool('flow_estimate', 'Estimate credits and image quota for planned jobs. Free.', LOCAL_READ, OBJECT({
    jobs: { type: 'array', description: 'Same arguments as the generate tools, plus kind: image (default) or video. Each needs a prompt; any short text will do. Image count is 1-4 per job, so split larger numbers.', items: { type: 'object' } },
  }, ['jobs'])),
  tool('flow_generate_image', 'Queue an image generation. Without auto_confirm: true it is a free dry run that touches nothing. Returns job_id at once; follow with flow_wait.', WRITE, OBJECT({
    prompt: { type: 'string' },
    model: { type: 'string', default: 'banana21', enum: ['banana21', 'bananaPro', 'banana2Lite'] },
    ratio: { type: 'string', default: '16:9', enum: ['16:9', '4:3', '1:1', '3:4', '9:16'] },
    count: { type: 'integer', default: 1, enum: [1, 2, 3, 4] },
    size: { type: 'string', default: '1K', enum: ['1K', '2K'] },
    ingredients: INGREDIENTS,
    max_generation_retries: { type: 'integer', default: 1, description: 'How many times a generation Flow failed is tried again by itself. Each try spends.' },
    ...SPEND,
  }, ['prompt'])),
  tool('flow_generate_video', 'Queue a video generation. CREDITS with auto_confirm: true; without it a free dry run that touches nothing.', WRITE, OBJECT({
    prompt: { type: 'string' },
    model: { type: 'string', default: 'omni', enum: ['omni', 'veoLite', 'veoFast', 'veoQuality'] },
    duration: { type: 'number', default: 8, description: 'Seconds. Veo takes only 8.' },
    resolution: { type: 'string', default: '720p', enum: ['720p', '360p'] },
    ratio: { type: 'string', default: '16:9', enum: ['16:9', '9:16'] },
    count: { type: 'integer', default: 1, enum: [1, 2, 3, 4] },
    ingredients: INGREDIENTS,
    start_frame: { type: 'string' },
    end_frame: { type: 'string' },
    extend_from: { type: 'string' },
    edit_from: { type: 'string' },
    silent: { type: 'boolean', default: false },
    ...SPEND,
  }, ['prompt'])),
  tool('flow_batch_start', 'Queue many jobs as one run from JSON or CSV. CREDITS.', WRITE, OBJECT({
    name: { type: 'string' },
    jobs: { type: 'array', description: 'Same arguments as the generate tools, plus kind: image (default) or video.', items: { type: 'object' } },
    file: { type: 'string', description: 'A .json list, or a .csv with a prompt column. CSV ingredients separate with ";": a path, character:Name or scene:Name.' },
    defaults: { type: 'object', description: 'Arguments every job starts from.' },
    project: { type: 'string', description: 'Flow project URL or title for every job.' },
    stop_on: { description: '"failure", or a list of error codes, holds the rest of the run as paused when a job fails that way. Default: only quota, limit and owner stops do.', oneOf: [{ type: 'string', enum: ['failure'] }, { type: 'array', items: { type: 'string' } }] },
    max_credits: SPEND.max_credits,
    auto_confirm: SPEND.auto_confirm,
    idempotency_key: SPEND.idempotency_key,
    output_root: SPEND.output_root,
  })),

  tool('flow_production_plan', 'Dry-run a Production from a moodboard file and a prompts file: parsed Cast and Shots, errors, what needs your judgement, estimate. Free, no browser.', LOCAL_READ, OBJECT({
    folder: { type: 'string', description: 'Holds *moodboard*.md and *animation*.md, *still*.md or *image*.md.' },
    moodboard_path: { type: 'string' },
    prompts_path: { type: 'string' },
    plan: { type: 'object', description: 'A whole plan { name, style, ratio, references: [{ id, kind, name, prompt }], shots: [{ id, kind: still or animation, refs, prompt }] }, for free-form files. Validated like parsed input.' },
    overrides: { type: 'object', description: '{ references: [{ id, kind, name, sheet_prompt, reuse, split_from }], shots: { <id>: { refs, start, reuse } } }. Split a row: give each half a new id with split_from, then set refs on the Shots that used it.' },
    defaults: { type: 'object', description: 'Animation defaults { model, duration, resolution }. Default omni, 6, 720p.' },
    name: { type: 'string' },
  })),
  tool('flow_production_start', 'Start a planned Production: References, then Stills, then silent Animations, each waiting for review. CREDITS when it has Animations. Returns at once; follow with flow_wait on run_id. The same plan_id returns the same Production.', SAME, OBJECT({
    plan_id: { type: 'string' },
    cast_confirmed: { type: 'boolean', description: 'true: I read both files and every Reference is exactly one subject.' },
    auto_confirm: { type: 'boolean', default: false, description: 'Must be true.' },
    max_credits: { type: 'number', description: 'Required with Animations: the cap on everything, regenerations included.' },
    project_url: { type: 'string', description: 'Flow project. Default a new one.' },
    output_root: SPEND.output_root,
    gates: { type: 'object', description: '{ references: true, stills: true }. false runs on without review at that stage.' },
    reference_mode: { type: 'string', enum: ['ingredient', 'character'], description: 'Default from config/production.json.' },
    new_run: { type: 'boolean', default: false, description: 'Start another Production from the same plan.' },
  }, ['plan_id'])),
  tool('flow_production_status', 'Status, per-stage counts, credits, what it waits on and the next action. Items only when filtered or with detail full, paged.', LOCAL_READ, OBJECT({
    production_id: { type: 'string', description: 'Default the latest.' },
    stage: { type: 'string', enum: ['reference', 'still', 'animation'] },
    state: { type: 'string', enum: ['planned', 'generating', 'pending_review', 'approved', 'rejected', 'regenerating', 'failed'] },
    detail: { type: 'string', enum: ['concise', 'full'], default: 'concise' },
    cursor: { type: 'integer', default: 0 },
    limit: { type: 'integer', default: 50, maximum: 50 },
  })),

  tool('flow_production_review', 'Approve or reject named Takes. Needs no browser. All or nothing: one illegal item changes none and is named. Only when the owner told you to.', hints(false, false, true, false), OBJECT({
    production_id: { type: 'string' },
    items: { type: 'array', description: '[{ id, take }]: a verdict names its Take, never "the latest".', items: { type: 'object' } },
    action: { type: 'string', enum: ['approve', 'reject'] },
    note: { type: 'string' },
  }, ['production_id', 'items', 'action'])),
  tool('flow_production_regenerate', 'Make a new Take of one Item, with its own prompt or a new one. Other Items and files are untouched. An Animation spends: dry_run shows the cost, auto_confirm: true spends. A repeat with the same expected_take returns the running Take.', SAME, OBJECT({
    production_id: { type: 'string' },
    item: { type: 'string' },
    prompt: { type: 'string', description: 'Omit to retry with the same prompt. The source files are never changed.' },
    expected_take: { type: 'integer', description: 'The latest Take you saw. Makes a repeat safe.' },
    auto_confirm: { type: 'boolean', default: false },
    dry_run: { type: 'boolean', default: false },
  }, ['production_id', 'item'])),

  tool('flow_job_status', 'State of a job, a run or a stitch. Concise by default.', LOCAL_READ, OBJECT({
    ...TARGET,
    stitch_id: STITCH_ID,
    detail: { type: 'string', enum: ['concise', 'full'], default: 'concise' },
    offset: { type: 'integer', default: 0, description: 'With detail full: first job of the page of 50.' },
  })),
  tool('flow_wait', 'Wait for a job, run or stitch to finish, or until wait_ms, then return its current state. Call again while finished is false.', LOCAL_READ, OBJECT({
    ...TARGET,
    stitch_id: STITCH_ID,
    wait_ms: { type: 'integer', default: 30000, minimum: 0, maximum: 55000 },
  })),
  tool('flow_job_control', 'pause, resume, cancel, retry_failed or set_budget. retry_failed may spend again. resume with no target restarts a stopped queue. set_budget raises a Production\'s cap, by run_id.', WRITE, OBJECT({
    action: { type: 'string', enum: ['pause', 'resume', 'cancel', 'retry_failed', 'set_budget'] },
    ...TARGET,
    stitch_id: { type: 'string', description: 'cancel only: stops a stitch and removes its partial file.' },
    max_credits: { type: 'number', default: 30, description: 'retry_failed: refuse if the regenerations estimate above this. set_budget: the new cap.' },
    accept_quote: { type: 'boolean', description: 'resume of a Production stopped on quote_drift: proceed at the price Flow quoted.' },
  }, ['action'])),
  tool('flow_list_runs', 'The most recent runs with job counts.', LOCAL_READ, OBJECT({ limit: { type: 'integer', default: 20, maximum: 50 } })),

  tool('flow_list_assets', 'List the assets of a run or Flow project. A run also lists its voice, music and effects under audio.', READ, OBJECT({ ...TARGET, project_url: { type: 'string' } })),
  tool('flow_download', 'Download an asset again, or the latest with latest: true. Repeats no generation.', SAME, OBJECT({ job_id: { type: 'string' }, latest: { type: 'boolean', default: false }, project_url: { type: 'string', description: 'With latest: the project. Default the open one.' } })),

  tool('flow_open_project', 'Open a Flow project, creating it when missing. Free.', SAME, OBJECT({
    url: { type: 'string' }, name: { type: 'string' }, create_if_missing: { type: 'boolean', default: true },
  })),
  tool('flow_list_projects', 'List Flow projects: [{ title, url }]. Free. Needs the Flow tab, so JOB_IN_PROGRESS means wait for the running job.', READ, OBJECT({ query: { type: 'string' } })),
  tool('flow_rename_project', 'Set a Flow project\'s title. Free.', SAME, OBJECT({ url: { type: 'string' }, name: { type: 'string' } }, ['url', 'name'])),
  tool('flow_delete_project', 'PERMANENT. Deletes a Flow project and its clips. Acts only with confirm: true, after the owner agreed.', DELETE, OBJECT({
    url: { type: 'string' }, confirm: { type: 'boolean', default: false },
  }, ['url'])),

  tool('flow_create_character', 'Create a named character in a project. Free from an image; a prompt alone spends.', WRITE, CHARACTER),
  tool('flow_list_characters', 'List a project\'s characters. Free.', READ, OBJECT({ project_url: { type: 'string' }, details: { type: 'boolean', default: false } }, ['project_url'])),
  tool('flow_import_character', 'Copy a character from another project. Free.', WRITE, OBJECT({
    project_url: { type: 'string' }, from_project_url: { type: 'string' }, name: { type: 'string' },
  }, ['project_url', 'from_project_url', 'name'])),
  tool('flow_create_scene', 'Create a reusable place as a character marked as a place. Free from an image; a prompt alone spends.', WRITE, CHARACTER),
  tool('flow_list_scenes', 'List a project\'s reusable places. Free.', READ, OBJECT({ project_url: { type: 'string' } }, ['project_url'])),

  tool('audio_voice_generate', 'Generate speech with Fish Audio and save it in the run\'s voice folder. Waits for the file. Stays on the free model unless model names another; never moves to a paid one by itself.', WRITE, OBJECT({
    text: { type: 'string' },
    script: { type: 'string', description: 'Same as text, for a longer narration. Long text is split at sentences and joined.' },
    voice_id: { type: 'string', description: 'From audio_voice_list.' },
    run_id: { type: 'string', description: 'Run to save in. Default a new run.' },
    name: { type: 'string' },
    format: { type: 'string', enum: ['mp3', 'wav', 'pcm', 'opus'], default: 'mp3' },
    speed: { type: 'number', minimum: 0.5, maximum: 2 },
    volume: { type: 'number', description: 'Decibels.' },
    temperature: { type: 'number', minimum: 0, maximum: 1 },
    top_p: { type: 'number', minimum: 0, maximum: 1 },
    model: { type: 'string', enum: ['s2.1-pro-free', 's2.1-pro', 's2-pro', 's1', 'drama-3'], default: 's2.1-pro-free', description: 'All but s2.1-pro-free cost money.' },
    language: { type: 'string', description: 'BCP-47 tag.' },
    output_root: SPEND.output_root,
  })),
  tool('audio_voice_list', 'List Fish Audio voices.', READ, OBJECT({
    query: { type: 'string', description: 'Filter by title.' },
    mine: { type: 'boolean', default: false, description: 'Only your own voices.' },
    limit: { type: 'number', default: 20, maximum: 100 },
  })),
  tool('audio_stable_generate', 'Generate music or sound effects with Stable Audio 3 and save them in the run\'s bgm or sfx folder. Waits for the file. 8 Stability credits each: without auto_confirm it only returns that estimate.', WRITE, OBJECT({
    kind: { type: 'string', enum: ['music', 'sfx'] },
    prompt: { type: 'string', description: 'English only.' },
    duration: { type: 'number', minimum: 1, maximum: 380, description: 'Seconds.' },
    seed: { type: 'number', minimum: 0, maximum: 4294967294 },
    steps: { type: 'integer', minimum: 4, maximum: 8, default: 8 },
    cfg_scale: { type: 'number', minimum: 1, maximum: 25, default: 1 },
    output_format: { type: 'string', enum: ['wav', 'mp3'], default: 'wav' },
    run_id: { type: 'string', description: 'Run to save in. Default a new run.' },
    name: { type: 'string' },
    auto_confirm: { type: 'boolean', default: false },
    output_root: SPEND.output_root,
  }, ['kind', 'prompt', 'duration'])),

  tool('stitch_video', 'Join a run\'s clips, voice, music and effects into one video in its final folder. Free. Returns stitch_id at once; follow with flow_wait on stitch_id, which ends with file. Originals are untouched.', SAME, OBJECT({
    run_id: { type: 'string' },
    auto: { type: 'boolean', description: 'Order the run\'s videos by sequence and add its voice and music.' },
    spec: { type: 'object', description: 'clips [{path, trim_start, trim_end, hold}], voice [{path, start}], bgm {path, volume, fade_out, duck}, sfx [{path, start, volume}], transition {type: fade, duration}, size, fps, loudness (default -14), output.' },
    name: { type: 'string' },
  }, ['run_id'])),
  tool('last_frame', 'Save the last frame of one of a run\'s videos as a PNG, for chaining as a start frame. Free.', SAME, OBJECT({
    run_id: { type: 'string' },
    asset_id: { type: 'string', description: 'job_id of a video in that run.' },
  }, ['run_id', 'asset_id'])),

  tool('flow_screenshot', 'Save a screenshot of the Flow tab. Never waits on a running job.', hints(true, false, false), OBJECT({ name: { type: 'string', default: 'manual' } })),
];

export const INSTRUCTIONS = 'Drives Google Flow through one shared local engine. flow_connect, then flow_capabilities. '
  + 'flow_generate_image without auto_confirm is a free dry run; with auto_confirm: true it queues and returns job_id at once. '
  + 'Then loop flow_wait until finished is true. Past submitted a job spends again only by flow_job_control retry_failed or within max_generation_retries (images default 1). '
  + 'For a whole video: flow_production_plan, answer analysis_needed, flow_production_start, watch with flow_wait on run_id, tell the owner to review, never approve unasked. '
  + 'Never try to get past verification or limits: tell the owner. Read the flow://guide resource for the full workflow.';
