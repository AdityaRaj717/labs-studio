import { finalPrompt } from './plan.js';

export { finalPrompt };

const DIRS = { reference: 'references', still: 'images', animation: 'videos' };

export const takeKey = (productionId, itemId, n) => `prod:${productionId}:${itemId}:take:${n}`;

const ingredientOf = (production, { item, file }) => {
  const { character } = production.items.find(({ id }) => id === item);
  return production.reference_mode === 'character' ? { character: character?.name } : { file };
};

// Take to job spec. deps comes from depsFor; every image is one result at 2K, every video silent.
export function composeJob(production, itemId, n, deps) {
  const item = production.items.find(({ id }) => id === itemId);
  const prompt = finalPrompt({ prompt: item.takes.find((take) => take.n === n)?.prompt ?? item.prompt }, production.style);
  const { max_credits: cap, spent } = production.budget;
  const common = {
    prompt,
    model: item.settings.model,
    ratio: production.ratio,
    count: 1,
    project_url: production.flow_project_url,
    auto_confirm: true,
    max_credits: cap === null ? item.estimate : Math.max(0, Math.min(item.estimate, cap - spent)),
    output: { dir: DIRS[item.stage], seq: item.seq, name: `${production.id}-${item.id}`, version: n },
  };
  const ingredients = deps.refs_used.map((used) => ingredientOf(production, used));
  if (item.stage !== 'animation') return { ...common, kind: 'image', size: '2K', ingredients };
  const { duration, resolution } = item.settings;
  const video = { ...common, kind: 'video', duration, resolution, silent: true };
  if (!deps.start_used) return { ...video, mode: 'ingredients', ingredients, ...(deps.end_used ? { end_frame: deps.end_used.file } : {}) };
  return { ...video, mode: 'frames', ingredients: [], start_frame: deps.start_used.file, ...(deps.end_used ? { end_frame: deps.end_used.file } : {}) };
}
