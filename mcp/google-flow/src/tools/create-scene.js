import { withJob, openProjectOrFail, listCharacters, createCharacter } from './create-character.js';
import { gotoProject } from './open-project.js';

// A "scene" here is a reusable place (the bunker, the street) for image work. Flow's own
// Scenes section holds video timelines and cannot be added to a prompt, so a place is kept
// as a Flow character marked as a place in its Character info (see create-character.js).

/** args: { project_url } -> { scenes: [{ name, info, url }] }. Opens each character to read its kind. Free. */
export async function handleListScenes(args = {}) {
  return withJob('list_scenes', { project_url: args.project_url }, async (page) => {
    const base = await openProjectOrFail(page, args.project_url);
    const scenes = (await listCharacters(page, base, true)).filter(c => c.kind === 'place')
      .map(({ name, info, url }) => ({ name, info, url }));
    await gotoProject(page, base);
    return { status: 'success', count: scenes.length, scenes };
  });
}

/** args: { project_url, name, prompt?, images?, info?, auto_confirm? }: like flow_create_character, as a place. */
export async function handleCreateScene(args = {}) {
  return withJob('create_scene', { project_url: args.project_url, name: args.name },
    page => createCharacter(page, { ...args, kind: 'place' }));
}
