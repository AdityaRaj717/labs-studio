import { test, before, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { contract, locate, closeOverlay, findSettingsGroup } from '../src/flow/contract.js';
import { runDoctor } from '../src/tools/doctor.js';
import { startFakeFlow } from './fake-flow/server.js';

let browser;
let page;
let flow;

before(async () => {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
after(() => browser.close());
afterEach(async () => {
  await page?.close();
  await flow?.close();
  page = flow = null;
});

async function open(path, scenario = 'default') {
  flow = await startFakeFlow({ scenario });
  page = await browser.newPage();
  await page.goto(flow.url + path);
}
const click = (key) => locate(page, key).click({ timeout: 3000 });
const clicks = async () => (await (await fetch(flow.url + '/__state')).json()).clicks;

async function assertResolved(prefixes, keys = Object.keys(contract.keys)) {
  const wanted = keys.filter((k) => prefixes.some((p) => k.startsWith(p)));
  assert.ok(wanted.length > 0, `no keys for ${prefixes}`);
  for (const key of wanted) {
    assert.ok((await locate(page, key).count()) > 0, `${key} did not resolve`);
  }
  return wanted;
}

test('locate resolves every contract key against fake Flow', { timeout: 60000 }, async () => {
  const seen = new Set();
  const see = async (prefixes) => (await assertResolved(prefixes)).forEach((k) => seen.add(k));

  await open('/');
  await see(['home.']);
  await page.getByRole('button', { name: 'Delete project', exact: true }).first().click();
  await see(['delete.']);
  await page.close(); await flow.close();

  await open('/project/p1', 'frames');
  await see(['project.chip.start', 'project.chip.end', 'project.chip.empty', 'project.swapFrames']);
  await page.close(); await flow.close();

  await open('/project/p1', 'chatOpen');
  await see(['project.chatClose', 'project.stop', 'project.chip.ingredient', 'project.promoDismiss']);
  await click('project.chatClose');
  await see(['project.agent', 'project.settingsTrigger', 'project.start', 'project.prompt',
    'project.addIngredients', 'project.tile', 'project.addMedia', 'project.title']);
  await click('project.addMedia');
  await see(['character.create']);
  await closeOverlay(page);

  await click('project.settingsTrigger');
  await see(['settings.kind.', 'settings.ratio.', 'settings.count.', 'settings.modelFamily',
    'settings.credits', 'settings.generatingWillUse']);
  await click('settings.modelFamily');
  await see(['settings.model.image']);
  await closeOverlay(page);
  await click('project.settingsTrigger');
  await locate(page, 'settings.kind.video').click();
  await see(['settings.mode.', 'settings.resolution.', 'settings.duration.']);
  await click('settings.modelFamily');
  await see(['settings.model.video']);
  await closeOverlay(page);

  await click('project.addIngredients');
  await see(['picker.']);
  await closeOverlay(page);
  await click('pageSettings.open');
  await see(['pageSettings.', 'overlay.backdrop', 'overlay.menu']);
  await closeOverlay(page);
  await click('account.open');
  await see(['account.', 'overlay.dialog']);
  await closeOverlay(page);
  await page.close(); await flow.close();

  await open('/project/p1/edit/m1');
  await see(['editor.addClip', 'editor.doneEditing', 'editor.editPrompt']);
  await click('editor.addClip');
  await see(['editor.menu.']);
  await click('editor.menu.extend');
  await see(['editor.exitExtend', 'editor.extendPrompt']);
  await page.close(); await flow.close();

  await open('/project/p1/character');
  await see(['character.prompt', 'character.upload', 'character.addFromProject', 'character.nav', 'character.section',
    'character.format', 'character.name', 'character.info', 'character.portrait', 'character.done']);

  const unseen = Object.keys(contract.keys).filter((k) => !seen.has(k));
  assert.deepEqual(unseen, []);
});

test('every contract entry has a page and one way to find it', () => {
  for (const [key, e] of Object.entries(contract.keys)) {
    assert.ok(e.page, `${key} has no page`);
    assert.equal([e.role, e.css, e.text].filter(Boolean).length, 1, `${key} needs exactly one of role, css, text`);
  }
});

test('locate rejects an unknown key', () => {
  assert.throws(() => locate({}, 'nope.nothing'), /nope\.nothing/);
});

test('delete.confirm is scoped to the dialog, not the project cards', async () => {
  await open('/');
  assert.equal(await locate(page, 'delete.confirm').count(), 0);
  await page.getByRole('button', { name: 'Delete project', exact: true }).first().click();
  assert.equal(await locate(page, 'delete.confirm').count(), 1);
});

test('findSettingsGroup finds image.count without index', async () => {
  await open('/project/p1');
  await click('project.settingsTrigger');
  const group = findSettingsGroup(page, 'image.count');
  assert.equal(await group.count(), 1);
  assert.equal(await group.getByRole('radio').count(), 4);
  assert.equal(await group.getByRole('radio', { name: 'x1', exact: true }).isChecked(), true);
});

test('findSettingsGroup tells image and video ratio apart', async () => {
  await open('/project/p1');
  await click('project.settingsTrigger');
  assert.equal(await findSettingsGroup(page, 'image.ratio').getByRole('radio').count(), 5);
  assert.equal(await findSettingsGroup(page, 'video.ratio').count(), 0);
  await locate(page, 'settings.kind.video').click();
  assert.equal(await findSettingsGroup(page, 'video.ratio').getByRole('radio').count(), 2);
  assert.equal(await findSettingsGroup(page, 'image.ratio').count(), 0);
  for (const key of ['kind', 'video.count', 'video.resolution', 'video.duration', 'video.mode']) {
    assert.equal(await findSettingsGroup(page, key).count(), 1, key);
  }
});

test('closeOverlay closes the settings panel on a page that ignores Escape', async () => {
  await open('/project/p1');
  await click('project.settingsTrigger');
  await page.keyboard.press('Escape');
  assert.equal(await locate(page, 'settings.kind.image').isVisible(), true, 'Escape must not close it');
  assert.equal(await closeOverlay(page), true);
  assert.equal(await locate(page, 'settings.kind.image').isVisible(), false);
});

test('closeOverlay closes a menu by backdrop and a panel by its control', async () => {
  await open('/project/p1');
  await click('pageSettings.open');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('menu').count(), 1);
  assert.equal(await closeOverlay(page), true);
  assert.equal(await page.getByRole('menu').count(), 0);

  await click('account.open');
  assert.equal(await closeOverlay(page), true);
  assert.equal(await page.getByRole('dialog').count(), 0);
  assert.equal((await clicks())['Close account panel'], 1);
});

test('closeOverlay unwinds a model menu inside settings', async () => {
  await open('/project/p1');
  await click('project.settingsTrigger');
  await click('settings.modelFamily');
  assert.equal(await closeOverlay(page), true);
  assert.equal(await page.getByRole('menu').count(), 0);
  assert.equal(await locate(page, 'settings.kind.image').isVisible(), false);
});

test('closeOverlay reports false when something stays open', async () => {
  await open('/project/p1', 'stuckMenu');
  await click('pageSettings.open');
  assert.equal(await closeOverlay(page), false);
});

test('fake Flow quote follows the findings cost table', async () => {
  await open('/project/p1');
  await click('project.settingsTrigger');
  const quote = () => locate(page, 'settings.credits').innerText();
  const pick = (name) => page.getByRole('radio', { name, exact: true }).click();
  const model = async (name) => {
    await click('settings.modelFamily');
    await page.getByRole('menuitem', { name, exact: true }).click();
  };
  assert.equal(await quote(), '0 credits');
  await locate(page, 'settings.kind.video').click();
  assert.equal(await quote(), '4 credits');
  await locate(page, 'settings.resolution.720p').click();
  assert.equal(await quote(), '7 credits');
  await pick('8s');
  assert.equal(await quote(), '12 credits');
  await pick('x2');
  assert.equal(await quote(), '24 credits');
  await pick('x1');
  await model('Veo 3.1 - Quality');
  assert.equal(await quote(), '100 credits');
  assert.equal(await page.getByRole('radio', { name: '8s', exact: true }).count(), 0, 'Veo has no duration');
  await model('Veo 3.1 - Lite');
  assert.equal(await quote(), '10 credits');
  await model('Veo 3.1 - Fast');
  assert.equal(await quote(), '20 credits');
});

const FORBIDDEN = ['Start generation', 'Add to prompt', 'Delete project', 'Save', 'New scene', 'Create character'];

test('doctor passes on a healthy project and clicks nothing that spends or saves', { timeout: 30000 }, async () => {
  await open('/project/p1', 'chatOpen');
  const result = await runDoctor(page);
  assert.deepEqual(result.missing, []);
  assert.equal(result.ok, true);
  assert.ok(result.checked > 10);
  assert.equal(result.host, new URL(flow.url).host);
  const seen = await clicks();
  for (const name of FORBIDDEN) assert.equal(seen[name], undefined, name);
  assert.equal(await locate(page, 'settings.kind.image').isVisible(), false, 'settings left open');
  assert.equal(await locate(page, 'picker.assetList').isVisible(), false, 'picker left open');
});

test('doctor works in frames mode, where the picker opens from a chip', { timeout: 30000 }, async () => {
  await open('/project/p1', 'frames');
  const result = await runDoctor(page);
  assert.deepEqual(result.missing, []);
});

test('doctor reports a missing Start button with its key', { timeout: 30000 }, async () => {
  await open('/project/p1', 'noStart');
  const result = await runDoctor(page);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, [{ key: 'project.start', where: 'project' }]);
});
