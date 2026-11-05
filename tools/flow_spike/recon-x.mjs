// Recon with spend: extend (10 credits) or edit (40). argv: extend|edit, prompt, optional path under the project to open first.
// Prints every change of the page's non-history aria lines and timeline DOM until argv minutes pass.
import * as y from './y0lib.mjs';
const [mode, prompt, open, minutes = '6'] = process.argv.slice(2);
const { browser, page } = await y.attach();
const base = 'https://flow.google.com/project/065acc3b-852c-4cf2-84c6-80359d0543bd';
if (open === 'first') {
  await page.goto(base, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(6000);
  await page.locator('img[alt="Generated video thumbnail"]').first().click(); await page.waitForTimeout(5000);
  console.log('opened', page.url());
} else if (open) { await page.goto(`${base}/${open}`, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(6000); }
const lines = async () => (await page.locator('body').ariaSnapshot()).split('\n').map((l) => l.trim()).filter((l) => !/^- (img|button) "[^"]*"(:)?$/.test(l) || /Download|Add clip|Done/.test(l));
if (mode === 'extend') {
  await page.getByRole('button', { name: 'Add clip' }).click();
  await page.waitForTimeout(800);
  console.log('menu', await page.getByRole('menuitem').allTextContents());
  await page.getByRole('menuitem', { name: /Extend/ }).click();
  await page.waitForTimeout(1500);
}
const box = page.getByRole('textbox', { name: mode === 'extend' ? 'What happens next?' : /Describe how to edit/ });
await box.click();
await page.keyboard.insertText(prompt);
await page.waitForTimeout(1000);
console.log('before', (await lines()).slice(-22).join(' | '));
console.log('credits text', await page.getByText(/\d+ credits?/).allTextContents());
await page.getByRole('button', { name: 'Start generation' }).click();
const started = Date.now();
let last = new Set();
while (Date.now() - started < Number(minutes) * 60000) {
  await page.waitForTimeout(5000);
  const now = await lines().catch(() => []);
  const set = new Set(now);
  const added = now.filter((l) => !last.has(l)); const gone = [...last].filter((l) => !set.has(l));
  const dom = await page.evaluate(() => ({ url: location.pathname.slice(-50), v: [...document.querySelectorAll('video')].map((v) => (v.currentSrc || v.src).slice(0, 60) + ' ' + v.duration), pct: (document.body.innerText.match(/\d+%/g) || []).slice(0, 3) })).catch((e) => e.message);
  if (added.length || gone.length) console.log(Math.round((Date.now() - started) / 1000), JSON.stringify(dom), '\n +', added.join(' | ').slice(0, 900), '\n -', gone.join(' | ').slice(0, 500));
  last = set;
}
console.log(page.url());
await browser.close(); process.exit(0);
