import fs from 'fs';
import { createError, ErrorCodes } from '../utils/errors.js';
import { getCapabilities } from './capabilities.js';

const { INVALID_PARAMS, MODEL_NOT_AVAILABLE, RATIO_NOT_AVAILABLE, COMBINATION_NOT_SUPPORTED } = ErrorCodes;

const fail = (code, message, valid, next_action) => {
  throw createError(code, message, { valid, next_action });
};

const isFile = (file) => {
  try {
    return fs.statSync(file).isFile();
  } catch {
    return false; // Missing, or not a usable path at all (null byte, wrong type).
  }
};

function requireFile(file, label) {
  if (!isFile(file)) fail(INVALID_PARAMS, `${label} is not a file: ${file}`, undefined, 'Pass the path of an existing file.');
}

function checkIngredients(ingredients = []) {
  if (!Array.isArray(ingredients)) fail(INVALID_PARAMS, 'ingredients must be a list', undefined, 'Pass ingredients as a list.');
  for (const item of ingredients) {
    if (typeof item === 'string' || item?.file !== undefined) requireFile(item?.file ?? item, 'ingredient');
    else if (!item?.character && !item?.scene && !item?.project) {
      fail(INVALID_PARAMS, 'an ingredient must be a file path or name a file, character, scene or project', undefined, 'Fix that ingredient.');
    }
  }
  return ingredients;
}

function checkCommon(args, caps, models) {
  const prompt = typeof args.prompt === 'string' ? args.prompt.trim() : '';
  if (!prompt) fail(INVALID_PARAMS, 'prompt must not be empty', undefined, 'Pass a prompt with text in it.');
  const { model = caps.defaultModel, ratio = caps.ratios[0], count = 1 } = args;
  if (!models.includes(model)) fail(MODEL_NOT_AVAILABLE, `unknown model: ${model}`, models, `Use one of: ${models.join(', ')}.`);
  if (!caps.ratios.includes(ratio)) fail(RATIO_NOT_AVAILABLE, `ratio ${ratio} is not available`, caps.ratios, `Use one of: ${caps.ratios.join(', ')}.`);
  if (!caps.counts.includes(count)) fail(INVALID_PARAMS, `count must be one of ${caps.counts.join(', ')}`, caps.counts, 'Use a count from 1 to 4.');
  return { ...args, prompt, model, ratio, count };
}

export function validateImage(args) {
  const { image: caps } = getCapabilities();
  const job = checkCommon(args, caps, caps.models);
  const { size = caps.sizes[0] } = args;
  if (!caps.sizes.includes(size)) {
    fail(COMBINATION_NOT_SUPPORTED, `image size ${size} is not available on Pro`, caps.sizes, `Use one of: ${caps.sizes.join(', ')}.`);
  }
  const retries = args.max_generation_retries;
  if (retries !== undefined && (!Number.isInteger(retries) || retries < 0)) {
    fail(INVALID_PARAMS, 'max_generation_retries must be a whole number, 0 or more', undefined, 'Pass 0 to never spend on a retry.');
  }
  return { ...job, kind: 'image', size, ingredients: checkIngredients(args.ingredients) };
}

function videoMode(args) {
  const modes = [];
  if (args.start_frame !== undefined || args.end_frame !== undefined) modes.push('frames');
  if (args.ingredients?.length > 0 || (args.ingredients !== undefined && !Array.isArray(args.ingredients))) modes.push('ingredients');
  if (args.extend_from) modes.push('extend');
  if (args.edit_from) modes.push('edit');
  if (modes.length > 1) fail(COMBINATION_NOT_SUPPORTED, `these can't be combined: ${modes.join(', ')}`, undefined, 'Pick one video mode.');
  return modes[0] ?? 'text';
}

export function validateVideo(args) {
  const { video: caps } = getCapabilities();
  const job = checkCommon(args, caps, Object.keys(caps.models));
  const { modes, defaults, credits } = caps.models[job.model];

  const mode = videoMode(args);
  if (!modes.includes(mode)) {
    fail(COMBINATION_NOT_SUPPORTED, `${job.model} does not support ${mode} mode`, modes, `Use one of: ${modes.join(', ')}, or another model.`);
  }

  const { duration = defaults.duration, resolution = defaults.resolution } = args;
  if (!Object.hasOwn(credits, resolution)) {
    const valid = Object.keys(credits);
    fail(COMBINATION_NOT_SUPPORTED, `${job.model} can't generate at resolution ${resolution} on Pro`, valid, `Use one of: ${valid.join(', ')}.`);
  }
  if (typeof duration !== 'number' || !Object.hasOwn(credits[resolution], duration)) {
    const valid = Object.keys(credits[resolution]).map(Number);
    fail(COMBINATION_NOT_SUPPORTED, `${job.model} can't generate ${duration} seconds on Pro`, valid, `Use a duration of: ${valid.join(', ')}.`);
  }

  for (const key of ['start_frame', 'end_frame']) {
    if (args[key] !== undefined) requireFile(args[key], key);
  }
  return { ...job, kind: 'video', mode, duration, resolution, ingredients: checkIngredients(args.ingredients) };
}
