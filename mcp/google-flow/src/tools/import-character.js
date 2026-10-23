import { logger } from '../utils/logger.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { withJob, openProjectOrFail, downloadPortrait, createCharacter, PLACE_PREFIX } from './create-character.js';
import { projectBase } from './open-project.js';

// Flow refuses to paste a character into another project, so an import rebuilds it: the
// portrait is downloaded from the source character and uploaded as a new character with the
// same name and info in the target project. Free (no generation).

/** args: { project_url, from_project_url, name } -> { name, created, url } */
export async function handleImportCharacter(args = {}) {
  const from = projectBase(args.from_project_url);
  if (!from) throw new FlowError(ErrorCodes.INVALID_PARAMS, `Not a Flow project URL: ${args.from_project_url}`);
  if (!args.name) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'name is required');
  if (projectBase(args.project_url) === from) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'Source and target are the same project');
  return withJob('import_character', { project_url: args.project_url, from_project_url: from, name: args.name }, async (page) => {
    await openProjectOrFail(page, from);
    const { file, info } = await downloadPortrait(page, from, args.name);
    logger.info('Character portrait saved for import', { name: args.name, file });
    const place = info.startsWith(PLACE_PREFIX);
    const result = await createCharacter(page, {
      project_url: args.project_url, name: args.name, images: [file],
      kind: place ? 'place' : 'person', info: place ? info.slice(PLACE_PREFIX.length) : info,
    });
    return { ...result, imported_from: from, portrait: file };
  });
}
