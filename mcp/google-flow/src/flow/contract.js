import { readFileSync } from 'node:fs';

export const contract = JSON.parse(readFileSync(new URL('../../config/ui-contract.json', import.meta.url), 'utf8'));

export function locate(page, key, opts = {}) {
  const entry = contract.keys[key];
  if (!entry) throw new Error(`Unknown UI contract key: ${key}`);
  const root = entry.within ? locate(page, entry.within) : opts.root ?? page;
  if (entry.css) return root.locator(entry.css);
  if (entry.text) return root.getByText(entry.text, { exact: true });
  if (!entry.name) return root.getByRole(entry.role);
  if (entry.name.regex) return root.getByRole(entry.role, { name: new RegExp(entry.name.regex) });
  return root.getByRole(entry.role, { name: entry.name, exact: true });
}

// Real radiogroups are unnamed, so a group is the one holding a known radio.
// image.count and video.count are the same control: only one kind shows at a time.
export function findSettingsGroup(page, key) {
  const group = contract.settingsGroups[key];
  if (!group) throw new Error(`Unknown settings group: ${key}`);
  const found = page.getByRole('radiogroup').filter({ has: locate(page, group.has) });
  return group.hasNot ? found.filter({ hasNot: locate(page, group.hasNot) }) : found;
}

const OPEN_MARKS = ['overlay.menu', 'overlay.dialog', 'settings.kind.image', 'picker.upload'];
const isShown = (page, key) => locate(page, key).first().isVisible();

async function anyOverlayOpen(page) {
  for (const key of OPEN_MARKS) if (await isShown(page, key)) return true;
  return false;
}

async function closeTopLayer(page) {
  for (const key of ['account.close', 'delete.cancel']) {
    if (await isShown(page, key)) return locate(page, key).click({ timeout: 2000 });
  }
  if (await isShown(page, 'overlay.backdrop')) {
    // Corner click: a panel over the centre could otherwise take the click on a real control.
    return locate(page, 'overlay.backdrop').last().click({ position: { x: 5, y: 5 }, timeout: 2000 });
  }
  if (await isShown(page, 'settings.kind.image')) return locate(page, 'project.settingsTrigger').click({ timeout: 2000 });
  if (await isShown(page, 'picker.upload')) return locate(page, 'project.addIngredients').click({ timeout: 2000 });
  return undefined;
}

// Flow ignores Escape. Returns whether everything really closed; the caller decides what that means.
export async function closeOverlay(page) {
  for (let attempt = 0; attempt < 5; attempt++) {
    if (!(await anyOverlayOpen(page))) return true;
    await closeTopLayer(page).catch(() => {});
    await page.waitForTimeout(200);
  }
  return !(await anyOverlayOpen(page));
}
