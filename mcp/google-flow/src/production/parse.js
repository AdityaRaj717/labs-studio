import fs from 'fs';
import path from 'path';
import { createError, ErrorCodes } from '../utils/errors.js';

const RATIO = /\b(16:9|4:3|1:1|3:4|9:16)\b/g;
const STYLE = /^style[^:]*:\s*(.+)$/i;
const SEPARATOR = /^\|?[\s:|-]+\|?$/;
const HEADING = /^(#{1,3})\s+(.+)$/;
const BLOCK_ID = /^([A-Za-z]+_[\w-]+|[A-Za-z]+\d[\w-]*)(?::\s*(.*))?$/;
const FIELD = /^(kind|name|prompt|type|refs|start|end|duration|model|resolution|line):\s*(.*)$/i;
const STILL_ID = /^(IMG|STILL|SHOT)_/i;
const ANIMATION_ID = /^(ANI|ANIM|VID)_/i;
const KINDS = { character: 'character', place: 'place', location: 'place' };
const SHOT_TYPES = { still: 'still', image: 'still', animation: 'animation', video: 'animation' };
const BRACKET_KIND = /\((character|location|place)\)/i;

const levelsOf = [/animation[^/\\]*\.md$/i, /still[^/\\]*\.md$/i, /image[^/\\]*\.md$/i];
const invalidFile = (message, details) => createError(ErrorCodes.PROMPT_FILE_INVALID, message, details);

export function discoverFiles(folder) {
  let names;
  try {
    names = fs.readdirSync(folder);
  } catch (err) {
    throw invalidFile(`Could not read the folder ${folder}: ${err.code ?? err.message}`);
  }
  const one = (matches, what) => {
    if (matches.length > 1) throw invalidFile(`Two ${what} files match at the same level: ${matches.join(', ')}`, { matches, next_action: 'Pass moodboard_path and prompts_path.' });
    return matches[0] && path.join(folder, matches[0]);
  };
  const moodboard = one(names.filter((name) => /moodboard[^/\\]*\.md$/i.test(name)), 'moodboard');
  const rest = names.filter((name) => !/moodboard/i.test(name));
  const level = levelsOf.map((pattern) => rest.filter((name) => pattern.test(name))).find((matches) => matches.length);
  const prompts = one(level ?? [], 'prompts');
  if (!moodboard || !prompts) throw invalidFile(`No ${moodboard ? 'prompts' : 'moodboard'} file in ${folder}`, { next_action: 'Pass moodboard_path and prompts_path.' });
  return { moodboard, prompts };
}

const decoder = new TextDecoder('utf-8', { fatal: true });

// Text, or the 1-based line of the first bytes that are not UTF-8.
function decode(input) {
  if (typeof input === 'string') return { text: input.replace(/^﻿/, '') };
  try {
    return { text: decoder.decode(input).replace(/^﻿/, '') };
  } catch {
    let line = 1;
    let start = 0;
    for (let i = 0; i <= input.length; i++) {
      if (i < input.length && input[i] !== 0x0a) continue;
      try {
        decoder.decode(input.subarray(start, i));
      } catch {
        return { badLine: line };
      }
      line++;
      start = i + 1;
    }
    return { badLine: 1 };
  }
}

// Cells of one table row; \| is a literal pipe.
function cellsOf(line) {
  const cells = [];
  let cell = '';
  const body = line.trim().replace(/^\|/, '');
  for (let i = 0; i < body.length; i++) {
    if (body[i] === '\\' && body[i + 1] === '|') { cell += '|'; i++; } else if (body[i] === '|') { cells.push(cell.trim()); cell = ''; } else cell += body[i];
  }
  if (cell.trim()) cells.push(cell.trim());
  return cells;
}

function isTableStart(lines, i) {
  return lines[i].includes('|') && i + 1 < lines.length && lines[i + 1].includes('-') && SEPARATOR.test(lines[i + 1].trim());
}

// Splits a file into its global text, table rows and blocks, in file order.
function scan(input, file) {
  const errors = [];
  const fail = (line, message) => errors.push({ file, line, code: ErrorCodes.PROMPT_FILE_INVALID, message });
  const { text, badLine } = decode(input);
  if (badLine) {
    fail(badLine, 'The file is not UTF-8');
    return { errors, warnings: [], title: null, style: null, ratio: null, entries: [], fail };
  }
  const lines = text.split(/\r?\n/);
  const entries = [];
  const global = [];
  let title = null;
  let section = null;
  let block = null;
  let seen = false;
  const closeBlock = () => { block = null; };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trim();
    const heading = HEADING.exec(line);
    if (isTableStart(lines, i)) {
      closeBlock();
      seen = true;
      const headers = cellsOf(lines[i]).map((h) => h.toLowerCase());
      i += 2;
      for (; i < lines.length && lines[i].includes('|'); i++) {
        const cells = cellsOf(lines[i]);
        if (cells.length !== headers.length) {
          fail(i + 1, `The row has ${cells.length} columns, the header ${headers.length}`);
          continue;
        }
        entries.push({ line: i + 1, section, table: true, fields: Object.fromEntries(headers.map((h, c) => [h, cells[c]])) });
      }
      i--;
    } else if (heading?.[1] === '#') {
      title ??= heading[2].trim();
    } else if (heading?.[1] === '##') {
      closeBlock();
      seen = true;
      section = heading[2].trim().toLowerCase();
    } else if (heading?.[1] === '###') {
      seen = true;
      const [, id, name] = BLOCK_ID.exec(heading[2].trim()) ?? [];
      block = { line: i + 1, section, heading: heading[2].trim(), id, name: id ? name : undefined, fields: {}, text: [] };
      entries.push(block);
    } else if (block && line) {
      const field = FIELD.exec(line);
      if (field) block.fields[field[1].toLowerCase()] = field[2].trim();
      else block.text.push(line);
    } else if (!seen && line) {
      global.push(line);
    }
  }

  const ratios = [...new Set(global.flatMap((line) => line.match(RATIO) ?? []))];
  if (ratios.length > 1) fail(1, `Two different ratios in the file's opening text: ${ratios.join(', ')}`);
  const style = global.map((line) => STYLE.exec(line)?.[1]).find(Boolean) ?? null;
  for (const entry of entries) {
    if (!entry.table) entry.fields.prompt ??= entry.text.join(' ');
  }
  if (!entries.length && !errors.length) fail(1, 'No table or block found');
  return { errors, warnings: [], title, style, ratio: ratios.length === 1 ? ratios[0] : null, entries, fail };
}

const slug = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '_').replace(/^_+|_+$/g, '');
const blank = (value) => value === undefined || value === '';

function noteDuplicate(seen, id, line, fail) {
  if (seen.has(id)) fail(line, `Duplicate ID ${id}`);
  seen.add(id);
}

export function parseMoodboard(input, file) {
  const scanned = scan(input, file);
  const { errors, warnings, style, ratio, entries, fail } = scanned;
  const title = scanned.title?.replace(/^moodboard:\s*/i, '') ?? null;
  const seen = new Set();
  const references = [];
  for (const entry of entries) {
    const { fields, line, section } = entry;
    const sectionKind = /^characters?\b/.test(section ?? '') ? 'character' : /^places?\b/.test(section ?? '') ? 'place' : null;
    let id = fields.id ?? entry.id;
    let name = fields.name || entry.name;
    if (!id) {
      if (sectionKind !== 'character') { fail(line, `No ID in "${entry.heading ?? 'row'}"`); continue; }
      id = `CH_${slug(entry.heading)}`;
      name ||= entry.heading;
    }
    noteDuplicate(seen, id, line, fail);
    const fixes = fields['what it fixes'] ?? '';
    let kind = null;
    if (fields.kind) {
      kind = KINDS[fields.kind.toLowerCase()] ?? null;
      if (!kind) fail(line, `Unknown Kind "${fields.kind}" on ${id}`);
    } else {
      kind = sectionKind ?? KINDS[BRACKET_KIND.exec(fixes)?.[1].toLowerCase()] ?? null;
    }
    if (blank(fields.prompt)) fail(line, `Empty prompt on ${id}`);
    references.push({ id, kind, name: name || fixes.split('(')[0].trim() || id, prompt: fields.prompt ?? '', line });
  }
  return { title, style, ratio, references, errors, warnings };
}

// null: no field. []: explicit none.
const refsOf = (cell) => {
  if (blank(cell)) return null;
  return cell.trim().toLowerCase() === 'none' ? [] : cell.split(',').map((s) => s.trim()).filter(Boolean);
};
// undefined: absent. null: explicit none.
const frameOf = (cell) => {
  if (blank(cell)) return undefined;
  return cell.trim().toLowerCase() === 'none' ? null : cell.trim();
};

function shotKind(id, typeCell, section, line, fail) {
  const byPrefix = STILL_ID.test(id) ? 'still' : ANIMATION_ID.test(id) ? 'animation' : null;
  const bySection = /^still/.test(section ?? '') ? 'still' : /^animation/.test(section ?? '') ? 'animation' : null;
  if (typeCell) {
    const type = SHOT_TYPES[typeCell.toLowerCase()];
    if (!type) fail(line, `Unknown Type "${typeCell}" on ${id}`);
    else if (byPrefix && byPrefix !== type) fail(line, `Type "${typeCell}" conflicts with the ID ${id}`);
    return type ?? byPrefix;
  }
  const kind = bySection ?? byPrefix;
  if (!kind) fail(line, `${id} has no Type, section or ID prefix that says still or animation`);
  return kind;
}

function shotOf(id, kind, fields, line, extra = {}) {
  const duration = blank(fields.duration) ? undefined : Number(String(fields.duration).replace(/s$/i, ''));
  return {
    id,
    kind,
    prompt: fields.prompt ?? '',
    refs: refsOf(fields.refs),
    start: frameOf(fields.start),
    end: frameOf(fields.end),
    duration,
    model: fields.model || undefined,
    resolution: fields.resolution?.toLowerCase() || undefined,
    line_id: fields.line || undefined,
    line,
    ...extra,
  };
}

export function parseShots(input, file) {
  const { errors, warnings, style, ratio, entries, fail } = scan(input, file);
  const seen = new Set();
  const shots = [];
  const add = (shot) => {
    noteDuplicate(seen, shot.id, shot.line, fail);
    if (blank(shot.prompt)) fail(shot.line, `Empty prompt on ${shot.id}`);
    shots.push(shot);
  };
  for (const entry of entries) {
    const { fields, line, section } = entry;
    const id = fields.id ?? fields.scene ?? entry.id;
    if (!id) { fail(line, `No ID in "${entry.heading ?? 'row'}"`); continue; }
    if ('image prompt' in fields) {
      const still = { ...fields, prompt: fields['image prompt'] };
      const animation = { ...fields, prompt: fields['animation prompt'], start: `${id}_IMG` };
      add(shotOf(`${id}_IMG`, 'still', still, line));
      add(shotOf(`${id}_ANI`, 'animation', animation, line));
      continue;
    }
    add(shotOf(id, shotKind(id, fields.type, section, line, fail), fields, line));
  }
  if (!shots.length && !errors.length) fail(1, 'No Shots in the file');
  return { ratio, style, shots, errors, warnings };
}
