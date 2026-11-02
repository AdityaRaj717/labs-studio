import { logger } from '../utils/logger.js';
import { getPage } from '../browser/connect.js';
import { jobQueue } from '../queue/job-queue.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { prepareDownload, saveMetadata } from '../utils/file-manager.js';
import { ensureProjectInContext } from '../navigation/project-navigator.js';
import { gotoProject } from './open-project.js';
import { get } from '../utils/config.js';
import fs from 'fs';
import path from 'path';

// Flow (Oct 2026) generates through each project's agent chat. A job:
//  1. open the project (campaign / project_name), never an /edit/ view
//  2. set the project's Agent settings: image aspect, count (x1-x4), image model and,
//     when auto_confirm, "Confirm before generating: Never" (these are per-project settings)
//  3. new chat session, clear leftover ingredients, upload reference images as ingredients
//  4. type the prompt, press "Start generation"
//  5. wait for the agent's reply bubble to finish (its "Good response" button appears)
//  6. download each image option at full size through Download media -> 1K / 2K
// Every label lives in UI below so a Flow UI change is a one-place edit.

const UI = {
  account: 'Account details',
  composer: 'What do you want to create?',
  newSession: 'Start new session',
  expandChat: 'Expand',
  clearPrompt: 'Clear prompt',
  start: 'Start generation',
  settings: 'Settings',
  settingsHeading: 'Agent settings',
  confirmNever: 'Never',
  imageAspectGroup: 1,
  imageCountGroup: 2,
  imageModelButton: 'Image generation default model',
  save: 'Save',
  ingredients: 'Add ingredients to the prompt box',
  ingredientChip: 'Ingredient',
  upload: 'Upload media',
  assetList: 'Asset list',
  addToPrompt: 'Add to prompt',
  searchAssets: 'Search assets',
  categories: 'Category navigation',
  charactersTab: 'Characters',
  selectProject: 'Select project',
  projectTitle: 'Editable text',
  bubble: 'flow-chat-bubble',
  replyText: 'flow-a2ui-text',
  done: 'Good response',
  gallery: 'Media options gallery',
  optionAlt: 'Option',
  openOption: 'Open image in editor',
  download: 'Download media',
  sizes: { '1K': '1K Original size', '2K': '2K Upscaled', '4K': '4K Upscaled' },
  backFromEditor: 'Back button to go to previous page',
};

const BLOCKS = {
  login: { url: ['accounts.google.com', 'flow.google.com/about'] },
  captcha: {
    url: ['google.com/sorry/', 'recaptcha'],
    text: ['unusual traffic from your computer', "verify you're not a robot", "i'm not a robot"],
  },
  quota: {
    text: ['reached your limit', 'reached your daily limit', 'out of credits', 'not enough credits',
      "don't have enough credits", 'try again tomorrow', 'quota exceeded'],
  },
};

// Old names still accepted: "Nano Banana 2" was renamed "Nano Banana 2.1".
const MODEL_ALIASES = { 'Nano Banana 2': 'Nano Banana 2.1', auto: 'Nano Banana 2.1' };
const REF_TEMPLATE = 'Use the attached image(s) as reference. Create a new {aspect} image: {prompt}';
const CHAR_TEMPLATE = 'Use the attached Flow characters and places ({names}) exactly as they are{refs}. Create a new {aspect} image: {prompt}';

function selectModel(requested) {
  const name = MODEL_ALIASES[requested || 'auto'] || requested;
  return get('imageModels', {})[name] ? name : null;
}

function selectRatio(requested) {
  const ratio = requested || '1:1';
  return get('ratios', []).includes(ratio) ? ratio : null;
}

const btn = (page, name) => page.getByRole('button', { name, exact: true });

async function need(page, locator, what, timeout = 15000) {
  try {
    await locator.waitFor({ state: 'visible', timeout });
    return locator;
  } catch {
    await takeScreenshot(page, 'ui-missing').catch(() => {});
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, `Flow UI not recognised: ${what} not found`, { what });
  }
}

function checkUrlBlock(url) {
  if (BLOCKS.login.url.some(u => url.includes(u))) {
    throw new FlowError(ErrorCodes.NOT_LOGGED_IN, 'Google Flow wants you to sign in. Sign in by hand in the Chrome window.');
  }
  if (BLOCKS.captcha.url.some(u => url.includes(u))) {
    throw new FlowError(ErrorCodes.MANUAL_VERIFICATION_REQUIRED, 'Google shows a CAPTCHA or bot check. Solve it by hand in the Chrome window.');
  }
}

function checkTextBlock(text) {
  const low = (text || '').toLowerCase();
  if (BLOCKS.captcha.text.some(t => low.includes(t))) {
    throw new FlowError(ErrorCodes.MANUAL_VERIFICATION_REQUIRED, 'Google shows a CAPTCHA or bot check. Solve it by hand in the Chrome window.');
  }
  if (BLOCKS.quota.text.some(t => low.includes(t))) {
    throw new FlowError(ErrorCodes.GOOGLE_LIMIT_REACHED, `Google Flow usage limit reached: ${text.slice(0, 200)}`);
  }
}

// The chat as a list of turns, read from the DOM: { agent, done, images: [src], text }.
async function readChat(page) {
  return page.evaluate((ui) => {
    const turns = [];
    for (const b of document.querySelectorAll(ui.bubble)) {
      if (b.parentElement && b.parentElement.closest(ui.bubble)) continue;
      const gallery = b.querySelector(`[aria-label="${ui.gallery}"]`);
      const images = gallery
        ? [...gallery.querySelectorAll('img')].filter(i => (i.alt || '').startsWith(ui.optionAlt)).map(i => i.src)
        : [];
      const done = !!b.querySelector(`[aria-label="${ui.done}"]`);
      const replies = [...b.querySelectorAll(ui.replyText)].map(e => e.innerText.trim()).filter(Boolean);
      const agent = done || !!gallery || replies.length > 0;
      turns.push({ agent, done, images, text: replies.join(' ') });
    }
    return turns;
  }, UI);
}

async function openProject(page, args) {
  if (args.project_url) {
    if (!await gotoProject(page, args.project_url)) {
      throw new FlowError(ErrorCodes.PROJECT_NOT_FOUND, `Flow project not found: ${args.project_url}`, { url: args.project_url });
    }
  } else {
    await ensureProjectInContext(page, { name: args.project_name, campaign: args.campaign });
  }
  const url = page.url();
  checkUrlBlock(url);
  // The image editor (/edit/...) and other sub-views have no agent composer: go to the grid.
  const m = url.match(/^(https:\/\/[^/]+\/project\/[^/?#]+)/);
  if (m && url.split('?')[0] !== m[1]) {
    await page.goto(m[1], { waitUntil: 'domcontentloaded', timeout: 60000 });
  }
  checkUrlBlock(page.url());
  const account = page.getByRole('button', { name: UI.account }).first();
  try {
    await account.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    throw new FlowError(ErrorCodes.NOT_LOGGED_IN, 'Google Flow is not signed in. Sign in by hand in the Chrome window.');
  }
  await need(page, page.getByRole('textbox', { name: UI.composer }).first(), 'agent prompt box', 20000);
}

// Returns true when the collapsed chat was expanded.
async function expandChat(page) {
  const expand = btn(page, UI.expandChat);
  if (!await expand.isVisible().catch(() => false)) return false;
  await expand.click().catch(() => {});
  await page.waitForTimeout(1200);
  return true;
}

async function applyAgentSettings(page, { ratio, count, model, neverConfirm }) {
  await need(page, btn(page, UI.settings).last(), 'agent Settings button');
  await btn(page, UI.settings).last().click();
  await need(page, page.getByRole('heading', { name: UI.settingsHeading }), 'Agent settings panel');
  if (neverConfirm) await page.getByRole('radio', { name: UI.confirmNever }).click();
  const groups = page.locator('[role=radiogroup]');
  await groups.nth(UI.imageAspectGroup).getByRole('radio', { name: ratio, exact: true }).click();
  await groups.nth(UI.imageCountGroup).getByRole('radio', { name: `x${count}`, exact: true }).click();
  const modelBtn = page.getByRole('button', { name: UI.imageModelButton });
  const current = await modelBtn.innerText().catch(() => '');
  if (!current.includes(model)) {
    await modelBtn.click();
    const item = page.getByRole('menuitem', { name: model });
    if (!await item.isVisible({ timeout: 5000 }).catch(() => false)) {
      throw new FlowError(ErrorCodes.MODEL_NOT_AVAILABLE, `Flow does not offer "${model}" in Agent settings`);
    }
    await item.click();
  }
  await btn(page, UI.save).click();
  await need(page, page.getByRole('textbox', { name: UI.composer }).first(), 'prompt box after saving settings');
  logger.info('Agent settings applied', { ratio, count, model, neverConfirm });
}

async function addReference(page, file) {
  if (!fs.existsSync(file)) throw new FlowError(ErrorCodes.INVALID_PARAMS, `Reference image not found: ${file}`);
  const chips = btn(page, UI.ingredientChip);
  const before = await chips.count();
  await btn(page, UI.ingredients).click();
  const upload = await need(page, page.getByRole('button', { name: UI.upload }), 'Upload media button');
  const name = path.basename(file);
  const option = page.getByRole('listbox', { name: UI.assetList })
    .getByRole('option', { name: `${name} Image`, exact: true }).first();
  const add = page.getByRole('button', { name: UI.addToPrompt });
  // Reuse a file already uploaded to this project (same file name) instead of uploading it again.
  const search = page.getByRole('textbox', { name: UI.searchAssets }).first();
  let reused = false;
  if (await search.isVisible().catch(() => false)) {
    await search.fill(name);
    await page.waitForTimeout(2000);
    if (await option.isVisible().catch(() => false)) {
      await option.click();
      await page.waitForTimeout(800);
      if (await chips.count() <= before && await add.isVisible().catch(() => false)) await add.click();
      reused = true;
    } else {
      await search.fill('');
    }
  }
  if (!reused) {
    const chooser = page.waitForEvent('filechooser', { timeout: 15000 });
    await upload.click();
    await (await chooser).setFiles(file);
  }
  const deadline = Date.now() + 120000;
  // A finished upload usually lands in the prompt by itself; otherwise select it (and press Add).
  while (await chips.count() <= before) {
    if (Date.now() > deadline) throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, `Reference ${name} never reached the prompt`);
    if (await option.isVisible().catch(() => false)) {
      await option.click();
      await page.waitForTimeout(1000);
      if (await chips.count() <= before && await add.isVisible().catch(() => false)) await add.click();
    }
    await page.waitForTimeout(1000);
  }
  const backdrop = page.locator('.cdk-overlay-backdrop');
  if (await backdrop.count()) await backdrop.last().click().catch(() => {});
  logger.info('Reference added', { file: name, reused });
}

// Add a Flow character (or a place kept as one) as an ingredient through the picker's
// Characters tab. entry: "Name" (this project) or { name, project } (another project's title).
async function addCharacter(page, entry) {
  const name = String(typeof entry === 'string' ? entry : entry.name || '').trim();
  if (!name) throw new FlowError(ErrorCodes.INVALID_PARAMS, `Character entry without a name: ${JSON.stringify(entry)}`);
  const chips = btn(page, UI.ingredientChip);
  const before = await chips.count();
  const here = (await page.getByRole('textbox', { name: UI.projectTitle }).first().inputValue().catch(() => '')).trim();
  const project = (typeof entry === 'object' && entry.project) || here;
  await btn(page, UI.ingredients).click();
  await need(page, page.getByRole('tablist', { name: UI.categories }), 'asset picker');
  // The picker remembers the last project it showed, so always set it.
  const switcher = page.getByRole('combobox', { name: UI.selectProject }).first();
  if (project && !(await switcher.innerText().catch(() => '')).includes(project)) {
    await switcher.click();
    const opt = page.getByRole('listbox', { name: UI.selectProject }).getByRole('option', { name: project, exact: true });
    if (!await opt.isVisible({ timeout: 5000 }).catch(() => false)) {
      await page.keyboard.press('Escape');
      throw new FlowError(ErrorCodes.PROJECT_NOT_FOUND, `No Flow project "${project}" in the picker's project switcher`, { project });
    }
    await opt.click();
    await page.waitForTimeout(1500);
  }
  await page.getByRole('tab', { name: UI.charactersTab, exact: true }).click();
  await page.getByRole('textbox', { name: UI.searchAssets }).first().fill(name);
  await page.waitForTimeout(2000);
  const option = page.getByRole('listbox', { name: UI.assetList }).getByRole('option', { name, exact: true }).first();
  if (!await option.isVisible().catch(() => false)) {
    await page.keyboard.press('Escape');
    throw new FlowError(ErrorCodes.INVALID_PARAMS, `No character "${name}" in Flow project "${project}". Create it with flow_create_character.`,
      { name, project });
  }
  await option.click();
  const add = page.getByRole('button', { name: UI.addToPrompt });
  const deadline = Date.now() + 20000;
  while (await chips.count() <= before) {
    if (Date.now() > deadline) throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, `Character ${name} never reached the prompt`);
    if (await add.isVisible().catch(() => false)) await add.click().catch(() => {});
    await page.waitForTimeout(700);
  }
  const backdrop = page.locator('.cdk-overlay-backdrop');
  if (await backdrop.count()) await backdrop.last().click().catch(() => {});
  logger.info('Character added', { name, project });
  return name;
}

async function downloadOptions(page, count, size, outputDir, base) {
  const files = [];
  const sizeLabel = UI.sizes[size] || UI.sizes['1K'];
  for (let i = 0; i < count; i++) {
    const gallery = page.getByRole('group', { name: UI.gallery }).last();
    await gallery.getByRole('button', { name: UI.openOption }).nth(i).click();
    await (await need(page, btn(page, UI.download), 'Download media button', 30000)).click();
    const item = await need(page, page.getByRole('menuitem', { name: sizeLabel }), `download size "${sizeLabel}"`);
    if (await item.isDisabled().catch(() => false)) {
      // Leave the page as it was: close the menu and the editor before failing.
      await page.keyboard.press('Escape');
      await btn(page, UI.backFromEditor).click().catch(() => {});
      throw new FlowError(ErrorCodes.INVALID_PARAMS, `Download size "${sizeLabel}" is not available on this plan`);
    }
    const dlPromise = page.waitForEvent('download', { timeout: 120000 });
    await item.click();
    const dl = await dlPromise;
    const ext = (path.extname(dl.suggestedFilename()) || '.jpg').toLowerCase().replace('.jpeg', '.jpg');
    const dest = path.join(outputDir, count === 1 ? `${base}${ext}` : `${base}_v${i + 1}${ext}`);
    await dl.saveAs(dest);
    files.push(dest);
    logger.info('Image saved', { path: dest, bytes: fs.statSync(dest).size });
    await btn(page, UI.backFromEditor).click();
    await need(page, page.getByRole('group', { name: UI.gallery }).last(), 'chat after download', 20000);
  }
  return files;
}

async function runGenerateImage(job, args) {
  const autoConfirm = args.auto_confirm === true;
  try {
    jobQueue.startJob(job.id);
    const page = getPage();

    const model = selectModel(args.model);
    if (!model) {
      throw new FlowError(ErrorCodes.MODEL_NOT_AVAILABLE,
        `Model "${args.model}" not available. Available: ${Object.keys(get('imageModels', {})).join(', ')}`,
        { requested: args.model });
    }
    const ratio = selectRatio(args.ratio);
    if (!ratio) {
      throw new FlowError(ErrorCodes.RATIO_NOT_AVAILABLE,
        `Ratio "${args.ratio}" not available. Available: ${get('ratios', []).join(', ')}`);
    }
    const count = Number(args.count ?? 1);
    if (!Number.isInteger(count) || count < 1 || count > 4) {
      throw new FlowError(ErrorCodes.INVALID_PARAMS, `count must be 1-4, got ${args.count}`);
    }
    const size = args.download_size || '1K';
    if (!UI.sizes[size]) throw new FlowError(ErrorCodes.INVALID_PARAMS, `download_size must be 1K, 2K or 4K, got ${size}`);
    const refs = args.reference_images || [];
    const characters = [...(args.characters || []), ...(args.scenes || [])];

    await openProject(page, args);
    args.onProjectOpen?.(page); // the flow stays in this project from here on
    await applyAgentSettings(page, { ratio, count, model, neverConfirm: autoConfirm });

    // The chat can be collapsed to just the prompt box; its reply bubbles only render when
    // expanded, so open it first (then "Start new session" shows too).
    await expandChat(page);
    // Fresh agent session per job so earlier chat context cannot leak into this prompt.
    // With no "Start new session" button the chat is empty: that already is a fresh session.
    const newSession = btn(page, UI.newSession);
    if (await newSession.isVisible().catch(() => false)) {
      await newSession.click();
      await page.waitForTimeout(1200);
    }
    const clear = btn(page, UI.clearPrompt);
    if (await clear.isVisible().catch(() => false)) {
      await clear.click();
      await page.waitForTimeout(500);
    }
    const charNames = [];
    for (const c of characters) charNames.push(await addCharacter(page, c));
    for (const ref of refs) await addReference(page, ref);

    const prompt = args.prompt.replace(/\s+/g, ' ').trim();
    // With references the agent tends to edit them and keep their shape, so say the aspect.
    let request = prompt;
    if (charNames.length) {
      request = CHAR_TEMPLATE.replace('{names}', charNames.join(', '))
        .replace('{refs}', refs.length ? ', and the attached image(s) as reference' : '')
        .replace('{aspect}', ratio).replace('{prompt}', prompt);
    } else if (refs.length) {
      request = REF_TEMPLATE.replace('{aspect}', ratio).replace('{prompt}', prompt);
    }
    const composer = await need(page, page.getByRole('textbox', { name: UI.composer }).first(), 'agent prompt box');
    await composer.click();
    await page.keyboard.insertText(request);
    const turnsBefore = (await readChat(page)).length;

    if (!autoConfirm) {
      const shot = await takeScreenshot(page, 'image-ready-for-confirmation');
      const result = {
        status: 'ready_for_confirmation', type: 'image',
        message: 'Settings applied and prompt typed. Nothing generated. Call again with auto_confirm=true.',
        model_used: model, ratio, count, references: refs.length, characters: charNames, prompt: args.prompt, request, screenshot: shot, jobId: job.id,
      };
      jobQueue.completeJob(job.id, result);
      return result;
    }

    const startBtn = btn(page, UI.start);
    const t0 = Date.now();
    while (!await startBtn.isEnabled().catch(() => false)) {
      if (Date.now() - t0 > 10000) {
        await takeScreenshot(page, 'no-generate-btn');
        throw new FlowError(ErrorCodes.GENERATION_BUTTON_DISABLED, '"Start generation" stayed disabled');
      }
      await page.waitForTimeout(250);
    }
    const outputDir = args.output_folder || prepareDownload('image', model, job.id).dir;
    fs.mkdirSync(outputDir, { recursive: true });
    await startBtn.click();
    logger.info('Generation started', { model, ratio, count, refs: refs.length });

    const timeoutMs = Number(args.timeout_ms) || get('generationTimeoutMs', 300000);
    let turn = null;
    while (Date.now() - t0 < timeoutMs) {
      await page.waitForTimeout(2000);
      checkUrlBlock(page.url());
      if (await expandChat(page)) await page.waitForTimeout(1500);
      const turns = await readChat(page);
      const last = turns.length > turnsBefore ? turns[turns.length - 1] : null;
      if (last && last.agent && last.done) { turn = last; break; }
    }
    if (!turn) {
      await takeScreenshot(page, 'generation-timeout');
      throw new FlowError(ErrorCodes.GENERATION_TIMEOUT, `No finished reply after ${Math.round(timeoutMs / 1000)}s`);
    }
    if (turn.images.length === 0) {
      checkTextBlock(turn.text);
      await takeScreenshot(page, 'no-images');
      throw new FlowError(ErrorCodes.GENERATION_REFUSED,
        `The agent replied without an image: ${turn.text.slice(0, 300) || '(no text)'}`, { reply: turn.text });
    }

    const base = (args.filename || `flow_${job.id}`).replace(/[\\/:*?"<>|]/g, '_');
    const files = await downloadOptions(page, turn.images.length, size, outputDir, base);
    if (files.length === 0) throw new FlowError(ErrorCodes.DOWNLOAD_FAILED, 'Images were generated but none could be downloaded');

    saveMetadata(job.id, { type: 'image', model, ratio, count, prompt: args.prompt, files, jobId: job.id });
    const result = {
      status: 'success', type: 'image', model_used: model, ratio, count_requested: count,
      download_size: size, references: refs.length, characters: charNames, prompt: args.prompt, agent_reply: turn.text,
      files, image_count: files.length, jobId: job.id,
    };
    jobQueue.completeJob(job.id, result);
    return result;
  } catch (err) {
    // getPage throws once the browser is gone; failJob must still run or the old queue sticks.
    await Promise.resolve().then(() => takeScreenshot(getPage(), 'generate-image-error')).catch(() => {});
    jobQueue.failJob(job.id, err);
    throw err;
  }
}

// Generation takes longer than most MCP hosts' request timeout, so the work runs in the
// background and this returns the result if it lands inside the response budget
// (wait_ms, else toolResponseBudgetMs); otherwise { status: 'running', jobId } and the
// result shows up in flow_queue_status history.
export async function handleGenerateImage(args) {
  const job = jobQueue.createJob('image_generation', {
    prompt: args.prompt,
    model: args.model || 'auto',
    ratio: args.ratio || '1:1',
    count: args.count || 1,
    auto_confirm: args.auto_confirm === true,
    outputFolder: args.output_folder,
    project_name: args.project_name,
    campaign: args.campaign,
    project_url: args.project_url,
  });

  const run = runGenerateImage(job, args);
  run.catch(err => logger.error('Background image job failed', { jobId: job.id, error: err.message }));
  // The engine worker hands the tab on only when the run has really ended.
  if (args.wait_for_run) return run;

  const budgetMs = Number(args.wait_ms) || get('toolResponseBudgetMs', 40000);
  const pending = Symbol('pending');
  const outcome = await Promise.race([run, new Promise(r => setTimeout(() => r(pending), budgetMs).unref())]);
  if (outcome === pending) {
    return {
      status: 'running',
      jobId: job.id,
      message: 'Still generating. Poll flow_queue_status; the result (files) appears in its history when done.',
    };
  }
  return outcome;
}
