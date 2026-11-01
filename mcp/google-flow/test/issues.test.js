import { test, before, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { startFakeFlow } from './fake-flow/server.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'flow-issues-'));
// Before any src import: config reads this once, and nothing may write into the checkout.
process.env.FLOW_DATA_DIR = tmp;
const load = (rel) => import(new URL(`../src/${rel}`, import.meta.url));

function sourceFiles(dir = path.join(root, 'src')) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? sourceFiles(full) : [full];
  });
}
const offenders = (pattern) => sourceFiles()
  .filter((f) => pattern.test(fs.readFileSync(f, 'utf8')))
  .map((f) => path.relative(root, f));

let browser;
let page;
let flow;

before(async () => {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
after(async () => {
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 3 });
});
afterEach(async () => {
  await page?.close();
  await flow?.close();
  page = flow = null;
});

async function open(urlPath, scenario = 'default') {
  flow = await startFakeFlow({ scenario });
  page = await browser.newPage();
  await page.goto(flow.url + urlPath);
}

test('no source file contains networkidle', () => {
  assert.deepEqual(offenders(/networkidle/), []);
});

test('no source file contains French labels or old hosts and names', () => {
  const french = /Nouveau|Projet|\bprojet\b|Outils|Personnages|Scènes|Corbeille|Modifier|Supprimer|Vidéo|Créer|Confirmer|Télécharger|CRÉDITS|CONSOMMENT|IMPOSSIBLE|fr-FR|\/fr\/|\bNom\b|\bnom\b|nouvelle-collection|ete-2026/;
  assert.deepEqual(offenders(french), []);
  assert.deepEqual(offenders(/labs\.google|launchKiaraProfile|Profile 3/), []);
});

test('deleted tools are gone', () => {
  assert.deepEqual(offenders(/flow_open_tools_gallery|flow_use_tool|flow_use_grid_architect|grid-architect/), []);
  for (const f of ['open-tools-gallery', 'use-flow-tool', 'grid-architect']) {
    assert.equal(fs.existsSync(path.join(root, 'src/tools', `${f}.js`)), false, f);
  }
});

test('isFlowHost accepts flow.google.com and nothing that looks like it', async () => {
  const { isFlowHost } = await load('browser/host.js');
  assert.equal(isFlowHost('https://flow.google.com/'), true);
  assert.equal(isFlowHost('https://flow.google.com/project/abc'), true);
  for (const url of [
    'https://flow.google.com.evil.test/', 'https://flow.google.com@evil.test/', 'https://evil.test/flow.google.com',
    'https://notflow.google.com/', 'http://flow.google.com/', 'https://labs.google/fx/tools/flow', 'about:blank', '', null,
  ]) assert.equal(isFlowHost(url), false, String(url));
});

test('isFlowHost accepts the fake host only when told to', async () => {
  const { isFlowHost } = await load('browser/host.js');
  assert.equal(isFlowHost('http://127.0.0.1:5000/'), false);
  assert.equal(isFlowHost('http://127.0.0.1:5000/', { testHost: '127.0.0.1:5000' }), true);
  assert.equal(isFlowHost('http://127.0.0.1:5001/', { testHost: '127.0.0.1:5000' }), false);
});

test('status with full:true includes a screenshot path', { timeout: 30000 }, async () => {
  const { setPage, setConnected } = await load('browser/connect.js');
  const { handleFlowStatus } = await load('tools/flow-status.js');
  await open('/');
  setPage(page);
  setConnected(true);
  process.env.FLOW_TEST_HOST = new URL(flow.url).host;
  try {
    const plain = await handleFlowStatus();
    assert.equal(plain.flowAccessible, true);
    assert.equal(plain.screenshot, undefined);
    const full = await handleFlowStatus({ full: true });
    assert.ok(fs.statSync(full.screenshot).size > 0);
  } finally {
    delete process.env.FLOW_TEST_HOST;
    setConnected(false);
    setPage(null);
  }
});

test('takeScreenshot returns null when the capture hangs', { timeout: 5000 }, async () => {
  const { takeScreenshot } = await load('utils/screenshots.js');
  const hung = { screenshot: () => new Promise(() => {}), context: () => ({ newCDPSession: async () => ({ send: () => new Promise(() => {}), detach: async () => {} }) }) };
  assert.equal(await takeScreenshot(hung, 'hung', 50), null);
});

test('delete waits for slow cards', { timeout: 30000 }, async () => {
  const { deleteFromHome } = await load('tools/open-project.js');
  await open('/', 'slowCards');
  const result = await deleteFromHome(page, `${flow.url}/project/p1`);
  assert.equal(result.status, 'success');
  assert.equal(await page.locator('a[href="/project/p1"]').count(), 0);
  assert.equal(await page.locator('a[href="/project/p2"]').count(), 1);
});

test('delete succeeds when list refresh is slow', { timeout: 30000 }, async () => {
  const { deleteFromHome } = await load('tools/open-project.js');
  await open('/', 'slowDelete');
  const result = await deleteFromHome(page, `${flow.url}/project/p1`);
  assert.equal(result.status, 'success');
});

test('delete reports a project that really is not listed', { timeout: 30000 }, async () => {
  const { deleteFromHome } = await load('tools/open-project.js');
  await open('/');
  await assert.rejects(deleteFromHome(page, `${flow.url}/project/nope`), { code: 'PROJECT_NOT_FOUND' });
});

test('waitForProjectCards sees cards that arrive after the New project button', { timeout: 30000 }, async () => {
  const { waitForProjectCards } = await load('navigation/project-navigator.js');
  await open('/', 'slowCards');
  await waitForProjectCards(page);
  assert.equal(await page.getByRole('link', { name: 'Open project', exact: true }).count(), 2);
});

test('account check fails when expected account is set and differs, and reports unverified when none is set', async () => {
  const { verifyAccount } = await load('browser/account-check.js');
  await open('/');
  await assert.rejects(verifyAccount(page, 'other@example.com'), { code: 'WRONG_GOOGLE_ACCOUNT' });
  const match = await verifyAccount(page, 'FAKE@example.com');
  assert.equal(match.status, 'ok');
  assert.equal(match.account, 'fake@example.com');
  const none = await verifyAccount(page, '');
  assert.equal(none.status, 'unverified');
  assert.equal(none.account, 'fake@example.com');
});

test('account check is unverified, not ok, when no account is shown', { timeout: 30000 }, async () => {
  const { verifyAccount } = await load('browser/account-check.js');
  await open('/project/p1/character');
  const result = await verifyAccount(page, 'fake@example.com');
  assert.equal(result.status, 'unverified');
  assert.equal(result.account, null);
});

const freePort = () => new Promise((resolve) => {
  const s = createServer();
  s.listen(0, '127.0.0.1', () => {
    const { port } = s.address();
    s.close(() => resolve(port));
  });
});

test("closing the MCP doesn't close Chrome", { timeout: 60000 }, async () => {
  const { connectToBrowser, closeBrowser, isBrowserConnected } = await load('browser/connect.js');
  const { get } = await load('utils/config.js');
  flow = await startFakeFlow();
  const port = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'flow-chrome-'));
  const chrome = spawn(get('chromePath'), [
    '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', flow.url,
  ], { stdio: 'ignore' });
  const debug = (p) => fetch(`http://127.0.0.1:${port}${p}`, { signal: AbortSignal.timeout(3000) });
  try {
    for (let i = 0; i < 40; i++) {
      if (await debug('/json/version').then((r) => r.ok, () => false)) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    await connectToBrowser({ cdpPort: port });
    assert.equal(isBrowserConnected(), true);
    await closeBrowser();
    assert.equal(isBrowserConnected(), false);
    await new Promise((r) => setTimeout(r, 1000));
    assert.equal((await debug('/json/version')).ok, true);
    const tabs = await (await debug('/json/list')).json();
    assert.ok(tabs.some((t) => t.url.startsWith(flow.url)), 'the Flow tab stays open');
  } finally {
    spawnSync('taskkill', ['/PID', String(chrome.pid), '/T', '/F']);
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
  }
});

test('config takes profile and port from env', () => {
  const script = "import('./src/utils/config.js').then(({ get }) => console.log(JSON.stringify([get('chromeProfileDir'), get('cdpPort')])))";
  const run = (env) => JSON.parse(spawnSync(process.execPath, ['-e', script], {
    cwd: root, encoding: 'utf8', env: { ...process.env, FLOW_CHROME_PROFILE: '', FLOW_CHROME_PROFILE_DIR: '', FLOW_CDP_PORT: '', ...env },
  }).stdout);
  assert.deepEqual(run({ FLOW_CHROME_PROFILE: 'X:/p', FLOW_CDP_PORT: '9444' }), ['X:/p', 9444]);
  assert.deepEqual(run({ FLOW_CHROME_PROFILE_DIR: 'X:/old' }), ['X:/old', 9333]);
  assert.deepEqual(run({}), ['D:/glabs_web/chrome-profile', 9333]);
});

test('launchFlowChrome replaces launchKiaraProfile', async () => {
  const mod = await load('browser/launch-profile.js');
  assert.equal(typeof mod.launchFlowChrome, 'function');
  assert.equal(mod.launchKiaraProfile, undefined);
});

test('example config has the video models and ratios', () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'config/flow.config.example.json'), 'utf8'));
  assert.equal(config.videoModels['Omni 1.1 Flash'], config.videoModels['Omni Flash']);
  assert.ok(config.videoModels['Omni 1.1 Flash']);
  assert.deepEqual(config.videoRatios, ['16:9', '9:16']);
});
