"""Site checks shared by the web-session code: selectors, block and login detection.

Generation itself runs in the google-flow MCP (``src/web/flow_mcp.py``). What is
here is what the app checks on its own: whether a site's tab shows a sign-in
wall, CAPTCHA or limit message, and whether the user is signed in. The pure
helpers work on HTML text, so they are tested on saved snapshots.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SELECTOR_DIR = Path(__file__).resolve().parent.parent / "selectors"

BLOCK_KINDS = ("captcha", "login", "quota")


def load_selectors(site: str, path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or SELECTOR_DIR / f"{site}.json").read_text(encoding="utf-8"))


class _TextGrabber(HTMLParser):
    """Visible-ish text of a page: skips script/style/template contents."""

    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def page_text(html: str) -> str:
    g = _TextGrabber()
    g.feed(html)
    return " ".join(g.parts)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def detect_block_text(text: str, url: str, rules: dict[str, Any]) -> str | None:
    """Return ``captcha`` / ``login`` / ``quota`` or None.

    ``rules`` is the selector JSON's ``block`` section: per kind a list of
    ``text`` phrases (case-insensitive) and ``url`` substrings.
    """
    low = _norm(text)
    for kind in BLOCK_KINDS:
        rule = rules.get(kind) or {}
        if any(u in url for u in rule.get("url", [])):
            return kind
        if any(_norm(p) in low for p in rule.get("text", [])):
            return kind
    return None


def detect_block_html(html: str, url: str, rules: dict[str, Any]) -> str | None:
    return detect_block_text(page_text(html), url, rules)


BLOCK_MESSAGES = {
    "captcha": "{site} is showing a CAPTCHA or bot check. Solve it yourself in the Chrome window, then start again.",
    "login": "{site} wants you to sign in. Sign in by hand in the Chrome window (Settings → Web Sessions → Launch browser), then start again.",
    "quota": "{site} says the usage limit is reached. The queue was stopped; try again later.",
}


def logged_in_html(html: str, sel: dict[str, Any]) -> bool:
    return f'aria-label="{sel["account_button"]}"' in html


def page_status(page, site: str) -> str:
    """``ok``, or ``login`` / ``captcha`` / ``quota``, for the site's tab (runs on its thread)."""
    sel = load_selectors(site)
    kind = detect_block_text(page.locator("body").inner_text(timeout=10000), page.url, sel.get("block", {}))
    if kind:
        return kind
    try:
        page.get_by_role("button", name=sel["account_button"]).first.wait_for(state="visible", timeout=8000)
    except Exception:  # noqa: BLE001 - Playwright TimeoutError
        return "login"
    return "ok"
