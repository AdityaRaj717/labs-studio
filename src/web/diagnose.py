"""Snapshot a site's tab for fixing selectors.

Writes ``<diag_dir>/<site>-<time>/`` with:
- ``screenshot.png``: what the page looks like
- ``page.html``: the DOM (also usable as a test fixture)
- ``aria.txt``: Playwright's accessibility snapshot of ``<body>``
- ``controls.json``: every visible button, input, link and menu item with its
  role, text, aria-label and a few attributes, the quickest way to pick selectors
- ``url.txt``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

CONTROLS_JS = """
() => {
  const out = [];
  const sel = 'button, a[href], input, textarea, select, [role=button], [role=menuitem], '
            + '[role=option], [role=tab], [role=combobox], [role=textbox], [contenteditable=true], img, video';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const pick = (n) => el.getAttribute(n);
    out.push({
      tag: el.tagName.toLowerCase(), role: pick('role'), text: (el.innerText || '').trim().slice(0, 120),
      aria: pick('aria-label'), title: pick('title'), placeholder: pick('placeholder'),
      type: pick('type'), id: el.id || null, testid: pick('data-testid'),
      src: el.tagName === 'IMG' || el.tagName === 'VIDEO' ? (el.currentSrc || el.src || '').slice(0, 200) : null,
      cls: (el.className && el.className.baseVal === undefined ? el.className : '').toString().slice(0, 120),
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    });
  }
  return out;
}
"""


def diag_root() -> Path:
    from src import config

    return Path(config.get("web.diag_dir", r"D:\glabs_web\diag"))


def capture(page, site: str, root: Path | None = None) -> Path:
    """Save the snapshot files for ``page`` (call on the site's thread)."""
    folder = (root or diag_root()) / f"{site}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "url.txt").write_text(page.url, encoding="utf-8")
    steps = {
        "screenshot.png": lambda: page.screenshot(path=str(folder / "screenshot.png"), full_page=False),
        "page.html": lambda: (folder / "page.html").write_text(page.content(), encoding="utf-8"),
        "aria.txt": lambda: (folder / "aria.txt").write_text(
            page.locator("body").aria_snapshot(timeout=15000), encoding="utf-8"),
        "controls.json": lambda: (folder / "controls.json").write_text(
            json.dumps(page.evaluate(CONTROLS_JS), indent=1, ensure_ascii=False), encoding="utf-8"),
    }
    for name, step in steps.items():
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - keep whatever else we can save
            log.warning("diagnose: %s failed (%s)", name, exc)
    log.info("Diagnose snapshot for %s saved to %s", site, folder)
    return folder


def diagnose(site: str, session=None) -> Path:
    """Snapshot the site's tab through the shared browser session."""
    if session is None:
        from src.web.session import session as get_session

        session = get_session()
    return session.run(site, lambda page: capture(page, site), timeout=120)
