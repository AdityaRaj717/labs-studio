// Y0 step 1: new project, one Reference Sheet (MD_02) and the place (MD_01), downloaded at 2K.
import * as y from './y0lib.mjs';

const SHEET = "Character reference sheet of a tired man in his early 30s, short messy dark hair, stubble, olive military-surplus jacket over a grey hoodie, fingerless gloves, small scar on the left eyebrow, cinematic photoreal. One image showing the same person as full-body front, side and back views plus a head close-up. Show the full outfit, proportions and every defining detail. Neutral pose, plain light background, even light, no text, no labels.";
const PLACE = 'Cramped concrete survival bunker interior, steel bunk bed, shelves of canned food and water jugs, a single caged bulb and candles, rusted vent grille, round steel hatch in the ceiling with a ladder, cinematic photoreal, 35mm film grain, teal shadows and warm amber light, no people';

const { browser, page } = await y.attach();
if (!page.url().includes('/project/')) {
  await page.goto('https://flow.google.com/', { waitUntil: 'domcontentloaded' });
  await y.locate(page, 'home.newProject').click();
  await page.waitForURL(/\/project\//, { timeout: 30000 });
}
console.log('project', page.url());
await y.locate(page, 'project.title').waitFor({ timeout: 30000 });
await y.locate(page, 'project.title').click();
await page.keyboard.press('Control+A');
await page.keyboard.insertText('y0-2026-11-02');
await page.keyboard.press('Enter');
await y.directMode(page);
console.log(await y.settings(page, { kind: 'image', model: 'banana21', ratio: '16:9', count: 1 }));
for (const [name, prompt] of [['y0-sheet-md02', SHEET], ['y0-place-md01', PLACE]]) {
  await y.typePrompt(page, prompt);
  const r = await y.submitAndWait(page, 1);
  console.log(name, r.ok, r.seconds ?? r.reason, r.log.slice(-2));
  if (!r.ok) { await y.snap(page, `${name}-fail`); process.exit(1); }
  console.log(await y.download(page, 0, '2K', name));
}
await y.snap(page, 'after-step1');
await browser.disconnect?.();
process.exit(0);
