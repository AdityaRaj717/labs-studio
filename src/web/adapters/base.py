"""SiteAdapter: what a web-session provider needs from one site.

An adapter wraps a Playwright page (on the site's worker thread) plus that
site's selector JSON. The pure helpers here work on HTML text, so block
detection and result parsing can be tested on saved snapshots without a browser.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

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


class SiteBlocked(Exception):
    """The site shows a CAPTCHA, a sign-in wall or a limit message."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class UiChanged(Exception):
    """An expected control is missing: the site's UI probably changed."""


class GenerationRefused(Exception):
    """The site refused this prompt (policy filter, unusable reference...)."""


class SiteAdapter:
    """Base class; one instance per job, used only on the site's thread."""

    site = "base"
    title = "Site"

    def __init__(self, page, selectors: dict[str, Any] | None = None):
        self.page = page
        self.sel = selectors if selectors is not None else load_selectors(self.site)

    # ---- state ---------------------------------------------------------
    def detect_block(self) -> str | None:
        return detect_block_text(self.page.locator("body").inner_text(timeout=10000),
                                 self.page.url, self.sel.get("block", {}))

    def is_logged_in(self) -> bool:
        raise NotImplementedError

    # ---- a job ----------------------------------------------------------
    def prepare(self) -> None:
        """Get the tab to where jobs start (before block and login checks)."""

    def submit(self, prompt: str, refs: list[Path], opts: dict[str, Any]) -> None:
        raise NotImplementedError

    def wait_done(self, timeout: float, should_stop: Callable[[], bool],
                  progress: Callable[[float], None] = lambda p: None) -> None:
        raise NotImplementedError

    def collect(self) -> list[tuple[bytes, str]]:
        """Return the new results as ``(data, ext)`` pairs."""
        raise NotImplementedError
