import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';

// Every scenario switch lives here; pages read them as window.FAKE.
const SCENARIOS = {
  default: {},
  frames: { kind: 'video', mode: 'frames' },
  chatOpen: { chatOpen: true, running: true, ingredient: true, promo: true },
  noStart: { noStart: true },
  stuckMenu: { stuckMenu: true },
  slowCards: { cardDelayMs: 4000 },
  slowDelete: { refreshDelayMs: 4000 },
};

const readPage = (name) => readFileSync(new URL(`./pages/${name}.html`, import.meta.url), 'utf8');

function pageFor(path) {
  if (/^\/project\/[^/]+\/edit\//.test(path)) return 'editor';
  if (/^\/project\/[^/]+\/character/.test(path)) return 'character';
  if (path.startsWith('/project/')) return 'project';
  return path === '/' ? 'home' : null;
}

// Synchronous so a test reading /__state right after a click can't race the report.
const CLICK_RECORDER = `document.addEventListener('click', (e) => {
  const el = e.target.closest('button,a,[role=radio],[role=menuitem],[role=tab]');
  if (!el) return;
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/__click', false);
  xhr.send(el.getAttribute('aria-label') || el.textContent.trim());
}, true);`;

export async function startFakeFlow({ scenario = 'default' } = {}) {
  const flags = SCENARIOS[scenario];
  if (!flags) throw new Error(`Unknown fake Flow scenario: ${scenario}`);
  const state = { clicks: {} };

  const server = createServer((req, res) => {
    const path = new URL(req.url, 'http://x').pathname;
    if (path === '/__state') {
      res.setHeader('content-type', 'application/json');
      return res.end(JSON.stringify({ ...state, startClicks: state.clicks['Start generation'] || 0 }));
    }
    if (path === '/__click') {
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('end', () => {
        state.clicks[body] = (state.clicks[body] || 0) + 1;
        res.end();
      });
      return undefined;
    }
    const name = pageFor(path);
    if (!name) {
      res.statusCode = 404;
      return res.end();
    }
    res.setHeader('content-type', 'text/html; charset=utf-8');
    const head = `<script>window.FAKE=${JSON.stringify(flags)};${CLICK_RECORDER}</script>`;
    return res.end(readPage(name).replace('<!--fake-->', head));
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  let closed;
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    close: () => (closed ??= new Promise((resolve) => {
      server.closeAllConnections();
      server.close(resolve);
    })),
  };
}
