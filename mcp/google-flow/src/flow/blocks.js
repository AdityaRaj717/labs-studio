import { contract } from './contract.js';

const { rules, toastDismiss } = contract.blocks;
const matcher = (source) => new RegExp(source, 'i');

// Detection only: the caller stops with needs_user and the owner deals with the block.
export async function detectBlock(page) {
  const url = page.url();
  const urlRule = rules.find((rule) => rule.url && matcher(rule.url).test(url));
  // Origin and path only: sign-in query strings can carry an email or a token.
  if (urlRule) return { code: urlRule.code, text: url.split(/[?#]/)[0] };

  const alerts = await page.locator('[role=alert]').allInnerTexts();
  const toasts = await page.getByRole('button', { name: toastDismiss, exact: true }).locator('..').allInnerTexts();
  const notices = [...alerts, ...toasts].join('\n');
  // Tile text is left out: a failed tile stays in the grid and would match every later check.
  const body = await page.evaluate((tile) => {
    const copy = document.body.cloneNode(true);
    copy.querySelectorAll(`${tile}, script, style, noscript, template`).forEach((el) => el.remove());
    return copy.textContent ?? '';
  }, contract.keys['project.tile'].css);

  for (const rule of rules) {
    if (!rule.text) continue;
    // Rules without "anywhere" read notices only, so a limit word in a prompt or title can't stop a run.
    const found = matcher(rule.text).exec(rule.anywhere ? `${notices}\n${body}` : notices);
    if (found) return { code: rule.code, text: found[0] };
  }
  return null;
}
