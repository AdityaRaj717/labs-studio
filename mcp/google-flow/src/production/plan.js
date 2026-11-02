import { createHash } from 'crypto';
import fs from 'fs';
import path from 'path';
import { estimate } from '../engine/budget.js';
import { validateImage, validateVideo } from '../engine/validate.js';
import { getDataDir } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { discoverFiles, parseMoodboard, parseShots } from './parse.js';

const SHEET_TEMPLATE = 'Character reference sheet of {prompt}. One image showing the same person as full-body front, side and back views plus a head close-up. Show the full outfit, proportions and every defining detail. Neutral pose, plain light background, even light, no text, no labels.';
const ANIMATION_DEFAULTS = { model: 'omni', resolution: '720p', duration: 6 };
const IMAGE_SETTINGS = { model: 'banana21', size: '2K', count: 1 };
const DEFAULT_RATIO = '16:9';
// shortcut: rough pace from the live runs (about a minute an image, two a video), for the report only.
const ETA_MINUTES = { image: 1, video: 2 };

const CONFIG = new URL('../../config/production.json', import.meta.url);
export const productionConfig = () => JSON.parse(fs.readFileSync(CONFIG, 'utf8'));

const sha = (data) => createHash('sha256').update(data).digest('hex');
const planFile = (id) => path.join(getDataDir(), 'plans', `${id}.json`);
const escapeRegex = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const trimEnd = (text) => text.replace(/[.\s]+$/, '');

// Spec 4: the style goes on every final prompt, so a changed prompt keeps it too.
export const finalPrompt = ({ prompt }, style) => (style ? `${trimEnd(prompt)}. Style: ${style}` : prompt);

function readSource(file) {
  try {
    return fs.readFileSync(file);
  } catch (err) {
    throw createError(ErrorCodes.PROMPT_FILE_INVALID, `Could not read ${file}: ${err.code ?? err.message}`);
  }
}

// Labels as written in a prompts file; anything else goes to the validator, which lists the valid names.
function videoModel(text) {
  const key = text.toLowerCase();
  if (key.includes('omni')) return 'omni';
  if (key.includes('lite')) return 'veoLite';
  if (key.includes('fast')) return 'veoFast';
  if (key.includes('quality')) return 'veoQuality';
  return text;
}

function applyReferenceOverrides(references, overrides, fail) {
  let rows = references;
  const splits = new Set();
  for (const change of overrides) {
    if (change.split_from) {
      if (!references.some(({ id }) => id === change.split_from)) { fail(`Override splits unknown ID ${change.split_from}`); continue; }
      splits.add(change.split_from);
      const { split_from, ...row } = change;
      rows = [...rows, { prompt: references.find(({ id }) => id === split_from).prompt, name: row.id, ...row }];
    } else if (rows.some(({ id }) => id === change.id)) {
      rows = rows.map((row) => (row.id === change.id ? { ...row, ...change } : row));
    } else {
      fail(`Override names unknown ID ${change.id}`);
    }
  }
  return rows.filter(({ id }) => !splits.has(id));
}

function applyShotOverrides(shots, overrides, fail) {
  const out = shots.map((shot) => ({ ...shot, ...overrides[shot.id] }));
  for (const id of Object.keys(overrides)) {
    if (!shots.some((shot) => shot.id === id)) fail(`Override names unknown ID ${id}`);
  }
  return out;
}

function resolveRefs(shot, cast, report) {
  const { refs, prompt, id } = shot;
  if (refs) {
    return refs.flatMap((token) => {
      const found = cast.find((ref) => ref.id === token) ?? cast.find((ref) => ref.name === token);
      if (!found) report.error(shot, `${id} uses unknown ref ${token}`);
      return found ? [found.id] : [];
    });
  }
  const named = cast.filter(({ name }) => new RegExp(`(?<![\\p{L}\\p{N}])${escapeRegex(name)}(?![\\p{L}\\p{N}])`, 'u').test(prompt)).map((ref) => ref.id);
  if (named.length) shot.ref_source = 'name';
  return named;
}

function resolveFrame(shot, key, stills, shots, report) {
  const value = shot[key];
  if (value === undefined || value === null) return null;
  if (stills.has(value)) return value;
  const what = shots.some(({ id }) => id === value) ? 'is not a Still' : 'is unknown';
  report.error(shot, `${shot.id}: ${key === 'start' ? 'Start' : 'End'} ${value} ${what}`);
  return null;
}

function validateShot(shot, ratio, defaults, limits, report) {
  const { id, kind, start } = shot;
  const settings = kind === 'animation'
    ? {
      model: videoModel(shot.model ?? defaults.model),
      duration: shot.duration ?? defaults.duration,
      resolution: shot.resolution ?? defaults.resolution,
      ratio,
      count: 1,
    }
    : { ...IMAGE_SETTINGS, model: shot.model ?? IMAGE_SETTINGS.model, ratio };
  const usesIngredients = kind === 'still' || !start;
  const limit = limits[kind === 'still' ? 'image' : 'video'];
  if (usesIngredients && Number.isInteger(limit) && shot.refs.length > limit) {
    report.error(shot, `${id} has ${shot.refs.length} refs, the limit is ${limit}`);
  }
  // Placeholder ingredient: only the mode is checked here, the files exist later.
  const ingredients = kind === 'animation' && usesIngredients && shot.refs.length ? [{ character: 'x' }] : undefined;
  try {
    const spec = kind === 'animation'
      ? validateVideo({ prompt: shot.prompt || id, ...settings, ingredients })
      : validateImage({ prompt: shot.prompt || id, ...settings });
    return { settings, spec };
  } catch (err) {
    report.error(shot, `${id}: ${err.message}`, err.code);
    return { settings, spec: null };
  }
}

function resolve(input, { defaults, limits, overrides }) {
  const { files } = input;
  const errors = [...input.errors];
  const warnings = [...input.warnings];
  const analysis = [];
  const implied = [];
  const fail = (message) => errors.push({ file: null, line: null, code: ErrorCodes.PROMPT_FILE_INVALID, message });
  const report = {
    error: ({ line = null }, message, code = ErrorCodes.PROMPT_FILE_INVALID) => errors.push({ file: files.prompts ?? null, line, code, message }),
  };
  const references = applyReferenceOverrides(input.references, overrides.references ?? [], fail);
  const shots = applyShotOverrides(input.shots, overrides.shots ?? {}, fail);

  const ids = new Map();
  for (const item of [...references, ...shots]) {
    if (ids.has(item.id)) report.error(item, `Duplicate ID ${item.id} across the files`);
    ids.set(item.id, item);
  }
  if (!shots.length && !errors.length) fail('No Shots');
  const hasPeople = references.some(({ kind }) => kind === 'character');
  const stills = new Set(shots.filter(({ kind }) => kind === 'still').map(({ id }) => id));
  const specs = [];
  let imageCount = 0;
  let videoCount = 0;

  const docRefs = references.map((ref) => {
    if (!ref.kind) analysis.push({ item: ref.id, reason: 'Is this a character or a place? Pass overrides.references with its kind.' });
    const prompt = ref.sheet_prompt ?? (ref.kind === 'character' ? SHEET_TEMPLATE.replace('{prompt}', () => trimEnd(ref.prompt)) : ref.prompt);
    const settings = { ...IMAGE_SETTINGS, ratio: input.ratio };
    if (!ref.reuse) {
      specs.push({ kind: 'image', model: settings.model, count: 1 });
      imageCount++;
    }
    return { id: ref.id, kind: ref.kind ?? null, name: ref.name, prompt, source_prompt: ref.prompt, settings, estimate: 0, ...(ref.reuse ? { reuse: ref.reuse } : {}), line: ref.line ?? null };
  });

  const docShots = shots.map((raw) => {
    const shot = { ...raw };
    const explicitNone = Array.isArray(raw.refs) && raw.refs.length === 0;
    if (shot.kind === 'animation') {
      if (shot.start === undefined && /^ANI_/i.test(shot.id)) {
        const pair = shot.id.replace(/^ANI_/i, 'IMG_');
        if (stills.has(pair)) {
          shot.start = pair;
          implied.push({ item: shot.id, start: pair });
        }
      }
      shot.start = resolveFrame(shot, 'start', stills, shots, report);
      shot.end = resolveFrame(shot, 'end', stills, shots, report);
    } else {
      shot.start = null;
      shot.end = null;
    }
    shot.refs = resolveRefs(shot, references, report);
    if (!shot.refs.length && !explicitNone && !shot.start) {
      if (hasPeople) analysis.push({ item: shot.id, reason: 'No Refs and no exact name in the prompt. Pass overrides.shots with its refs, or refs: [] for none.' });
      else warnings.push({ file: files.prompts ?? null, line: shot.line ?? null, message: `${shot.id} has no refs` });
    }
    if (shot.reuse && shot.kind !== 'still') report.error(shot, `${shot.id}: only a Reference or a Still can be reused`);
    const { settings, spec } = validateShot(shot, input.ratio, defaults, limits, report);
    let credits = 0;
    if (spec) {
      credits = estimate([spec]).credits;
      if (!shot.reuse) specs.push(spec);
    }
    if (!shot.reuse) { if (shot.kind === 'animation') videoCount++; else imageCount++; }
    return {
      id: shot.id,
      kind: shot.kind,
      prompt: shot.prompt,
      refs: shot.refs,
      ...(shot.ref_source ? { ref_source: shot.ref_source } : {}),
      start: shot.start,
      end: shot.end,
      settings,
      estimate: credits,
      line_id: shot.line_id ?? null,
      line: shot.line ?? null,
      ...(shot.reuse ? { reuse: shot.reuse } : {}),
    };
  });

  const used = new Set(docShots.flatMap(({ refs }) => refs));
  for (const { id, line } of docRefs) {
    if (!used.has(id)) warnings.push({ file: files.moodboard ?? null, line, message: `No Shot uses ${id}` });
  }
  const totals = estimate(specs);
  const byModel = {};
  for (const spec of docShots) {
    if (spec.estimate && !spec.reuse) byModel[spec.settings.model] = (byModel[spec.settings.model] ?? 0) + spec.estimate;
  }
  return {
    errors,
    warnings,
    analysis,
    implied,
    references: docRefs,
    shots: docShots,
    estimate: {
      credits: totals.credits,
      credits_by_model: byModel,
      image_quota: totals.imageQuota,
      two_k: imageCount,
      eta_minutes: imageCount * ETA_MINUTES.image + videoCount * ETA_MINUTES.video,
      warnings: totals.warnings,
    },
  };
}

function inputOf({ folder, moodboard_path, prompts_path, plan, name }) {
  const paths = moodboard_path && prompts_path ? { moodboard: moodboard_path, prompts: prompts_path } : (folder ? discoverFiles(folder) : null);
  if (!paths && !plan) throw createError(ErrorCodes.INVALID_PARAMS, 'Pass folder, moodboard_path and prompts_path, or plan');
  const files = paths ? { moodboard: path.resolve(paths.moodboard), prompts: path.resolve(paths.prompts) } : {};
  const buffers = paths ? [readSource(files.moodboard), readSource(files.prompts)] : [];
  const sources = paths ? [files.moodboard, files.prompts].map((file, i) => ({ path: file, sha256: sha(buffers[i]) })) : [];
  const warnings = [];
  if (plan) {
    const text = buffers.map((buffer) => buffer.toString('utf8')).join('\n');
    if (paths) {
      for (const { id, prompt } of [...(plan.references ?? []), ...(plan.shots ?? [])]) {
        if (!text.includes(prompt)) warnings.push({ file: null, line: null, message: `The plan's prompt for ${id} is not in the source files` });
      }
    }
    if (!plan.ratio) warnings.push({ file: null, line: null, message: `No ratio, using ${DEFAULT_RATIO}` });
    return {
      files, sources, warnings, errors: [], title: plan.name, style: plan.style ?? null,
      ratio: plan.ratio ?? DEFAULT_RATIO,
      references: (plan.references ?? []).map((ref) => ({ kind: null, name: ref.id, ...ref })),
      shots: (plan.shots ?? []).map((shot) => ({ refs: null, ...shot })),
      fallbackName: 'production',
    };
  }
  const mood = parseMoodboard(buffers[0], files.moodboard);
  const shots = parseShots(buffers[1], files.prompts);
  const ratio = shots.ratio ?? mood.ratio;
  if (!ratio) warnings.push({ file: files.prompts, line: null, message: `No ratio in the files, using ${DEFAULT_RATIO}` });
  return {
    files, sources, warnings: [...warnings, ...mood.warnings, ...shots.warnings], errors: [...mood.errors, ...shots.errors],
    title: mood.title, style: mood.style ?? shots.style, ratio: ratio ?? DEFAULT_RATIO,
    references: mood.references, shots: shots.shots,
    fallbackName: path.basename(path.dirname(files.moodboard)),
  };
}

// Never touches a browser. A plan with errors is reported but not kept, so it can't start.
export function buildPlan(args = {}) {
  const { overrides = {}, defaults = {}, name } = args;
  const input = inputOf(args);
  const merged = { ...ANIMATION_DEFAULTS, ...defaults };
  const result = resolve(input, { defaults: merged, limits: productionConfig().maxIngredients, overrides });
  const { errors, warnings, analysis, implied, references, shots } = result;
  const counts = {
    references: references.length,
    stills: shots.filter(({ kind }) => kind === 'still').length,
    animations: shots.filter(({ kind }) => kind === 'animation').length,
  };
  const mode = counts.animations ? 'mixed' : 'stills_only';
  const ok = errors.length === 0;
  const plan_id = ok
    ? sha(JSON.stringify({ sources: input.sources.map((s) => s.sha256), plan: args.plan ?? null, overrides, defaults, name: name ?? null })).slice(0, 16)
    : null;
  const report = {
    ok,
    plan_id,
    mode,
    counts,
    cast: references.map(({ id, name: refName, kind }) => ({ id, name: refName, kind })),
    errors,
    warnings,
    analysis_needed: analysis,
    implied,
    estimate: result.estimate,
  };
  if (ok) {
    const doc = {
      plan_id,
      name: name ?? input.title ?? input.fallbackName,
      mode,
      style: input.style,
      ratio: input.ratio,
      sources: input.sources,
      defaults: merged,
      references,
      shots,
      analysis_needed: analysis,
      estimate: result.estimate,
    };
    fs.mkdirSync(path.dirname(planFile(plan_id)), { recursive: true });
    fs.writeFileSync(planFile(plan_id), JSON.stringify(doc));
  }
  return report;
}

const planChanged = (message) => createError(ErrorCodes.PLAN_CHANGED, message, { next_action: 'Call flow_production_plan again and use its new plan_id.' });

export function loadPlan(planId) {
  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(planFile(String(planId).replace(/[^\w-]/g, '')), 'utf8'));
  } catch {
    throw planChanged(`No plan ${planId}`);
  }
  for (const { path: file, sha256 } of doc.sources) {
    let now;
    try {
      now = sha(fs.readFileSync(file));
    } catch {
      throw planChanged(`A source file of plan ${planId} is gone: ${file}`);
    }
    if (now !== sha256) throw planChanged(`A source file changed since plan ${planId}: ${file}`);
  }
  return doc;
}
