// Spec 6.4. stitch_video is left out until its task builds it.
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
    jobs: { type: 'array', description: 'Same arguments as the generate tools, plus kind: image (default) or video.', items: { type: 'object' } },
  }, ['jobs'])),
  tool('flow_generate_image', 'Queue an image generation. Returns job_id at once; follow with flow_wait.', WRITE, OBJECT({
    prompt: { type: 'string' },
    model: { type: 'string', default: 'banana21', enum: ['banana21', 'bananaPro', 'banana2Lite'] },
    ratio: { type: 'string', default: '16:9', enum: ['16:9', '4:3', '1:1', '3:4', '9:16'] },
    count: { type: 'integer', default: 1, enum: [1, 2, 3, 4] },
    size: { type: 'string', default: '1K', enum: ['1K', '2K'] },
    ingredients: INGREDIENTS,
    ...SPEND,
  }, ['prompt'])),
  tool('flow_generate_video', 'Queue a video generation. CREDITS.', WRITE, OBJECT({
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
  tool('flow_batch_start', 'Queue many jobs as one run from JSON or CSV. CREDITS.', WRITE, OBJECT({ jobs: { type: 'array', items: { type: 'object' } }, file: { type: 'string' }, ...SPEND })),

  tool('flow_job_status', 'State of a job or a run. Concise by default.', LOCAL_READ, OBJECT({
    ...TARGET,
    detail: { type: 'string', enum: ['concise', 'full'], default: 'concise' },
    offset: { type: 'integer', default: 0, description: 'With detail full: first job of the page of 50.' },
  })),
  tool('flow_wait', 'Wait for a job or run to finish, or until wait_ms, then return its current state. Call again while finished is false.', LOCAL_READ, OBJECT({
    ...TARGET,
    wait_ms: { type: 'integer', default: 30000, minimum: 0, maximum: 55000 },
  })),
  tool('flow_job_control', 'pause, resume, cancel or retry_failed. retry_failed may spend again. resume with no target restarts a stopped queue.', WRITE, OBJECT({
    action: { type: 'string', enum: ['pause', 'resume', 'cancel', 'retry_failed'] },
    ...TARGET,
  }, ['action'])),
  tool('flow_list_runs', 'The most recent runs with job counts.', LOCAL_READ, OBJECT({ limit: { type: 'integer', default: 20, maximum: 50 } })),

  tool('flow_list_assets', 'List the assets of a run or Flow project.', READ, OBJECT({ ...TARGET, project_url: { type: 'string' } })),
  tool('flow_download', 'Download an asset again, or the latest with latest: true. Repeats no generation.', SAME, OBJECT({ job_id: { type: 'string' }, latest: { type: 'boolean', default: false } })),

  tool('flow_open_project', 'Open a Flow project, creating it when missing. Free.', SAME, OBJECT({
    url: { type: 'string' }, name: { type: 'string' }, create_if_missing: { type: 'boolean', default: true },
  })),
  tool('flow_list_projects', 'List Flow projects: [{ title, url }]. Free.', READ, OBJECT({ query: { type: 'string' } })),
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

  tool('audio_voice_generate', 'Generate speech with Fish Audio.', WRITE, OBJECT({ text: { type: 'string' }, voice: { type: 'string' } }, ['text'])),
  tool('audio_voice_list', 'List available voices.', READ),
  tool('audio_stable_generate', 'Generate music or sound effects with Stability.', WRITE, OBJECT({
    kind: { type: 'string', enum: ['music', 'sfx'] }, prompt: { type: 'string' },
  }, ['kind', 'prompt'])),

  tool('flow_screenshot', 'Save a screenshot of the Flow tab. Never waits on a running job.', hints(true, false, false), OBJECT({ name: { type: 'string', default: 'manual' } })),
];

export const INSTRUCTIONS = 'Drives Google Flow through one shared local engine. flow_connect, then flow_capabilities. '
  + 'flow_generate_image without auto_confirm is a free dry run; with auto_confirm: true it queues and returns job_id at once. '
  + 'Then loop flow_wait until finished is true. Past submitted a job never spends again without flow_job_control retry_failed. '
  + 'Never try to get past verification or limits: tell the owner. Read the flow://guide resource for the full workflow.';
