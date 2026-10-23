"""Real Chrome over CDP for the web-session providers.

The app launches the user's own Chrome with a dedicated profile (on D: by
default) and ``--remote-debugging-port``, or attaches to it when it is already
running, then connects with Playwright's ``connect_over_cdp``. The user signs in
by hand in that window; nothing here types or stores a password.

Playwright's sync API is bound to the thread that started it, so each site gets
one worker thread that owns its own connection and tab. Everything that touches
the page runs there through ``BrowserSession.run``. A per-site lock lets a
provider hold the site for a whole job (cap check, gap, generate, count).
"""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

# site key -> (home URL, URL prefixes that count as "this site's tab")
SITES: dict[str, tuple[str, tuple[str, ...]]] = {
    "flow": ("https://labs.google/fx/tools/flow", ("https://labs.google/fx", "https://flow.google.com")),
}


class BrowserError(Exception):
    """Chrome could not be launched or reached."""


def _settings():
    from src import config

    return config.settings()


class _SiteWorker:
    """One thread, one Playwright connection, one tab for a site."""

    def __init__(self, session: "BrowserSession", site: str):
        self.session = session
        self.site = site
        self.tasks: queue.Queue = queue.Queue()
        self.pw = None
        self.browser = None
        self.page = None
        self.thread = threading.Thread(target=self._loop, name=f"web-{site}", daemon=True)
        self.thread.start()

    def submit(self, fn: Callable[[Any], Any]) -> Future:
        fut: Future = Future()
        self.tasks.put((fn, fut))
        return fut

    def stop(self) -> None:
        self.tasks.put(None)

    def _loop(self) -> None:
        while True:
            item = self.tasks.get()
            if item is None:
                break
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(self._ensure_page()))
            except BaseException as exc:  # noqa: BLE001 - handed to the caller
                if _is_disconnect(exc):
                    self._drop()
                fut.set_exception(exc)
        self._drop()

    def _ensure_page(self):
        if self.page is not None and not self.page.is_closed() and self.browser.is_connected():
            return self.page
        self._drop()
        from playwright.sync_api import sync_playwright

        self.session.ensure_running()
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(self.session.endpoint, timeout=15000)
        ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        home, prefixes = SITES[self.site]
        for p in ctx.pages:
            if p.url.startswith(prefixes):
                self.page = p
                break
        else:
            self.page = ctx.new_page()
            self.page.goto(home, wait_until="domcontentloaded", timeout=60000)
        log.info("Attached to Chrome tab for %s: %s", self.site, self.page.url)
        return self.page

    def _drop(self) -> None:
        self.page = None
        try:
            if self.pw is not None:
                self.pw.stop()  # disconnects; never closes the user's Chrome
        except Exception:  # noqa: BLE001
            log.debug("Playwright stop failed", exc_info=True)
        self.pw = None
        self.browser = None


def _is_disconnect(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(s in text for s in ("TargetClosed", "has been closed", "Browser closed", "disconnected"))


class BrowserSession:
    def __init__(self, store=None):
        self.store = store if store is not None else _settings()
        self._workers: dict[str, _SiteWorker] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # ---- settings ----------------------------------------------------
    @property
    def port(self) -> int:
        return int(self.store.get("web.port", 9333))

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def chrome_path(self) -> str:
        return str(self.store.get("web.chrome_path", ""))

    @property
    def profile_dir(self) -> Path:
        return Path(self.store.get("web.profile_dir", r"D:\glabs_web\chrome-profile"))

    # ---- Chrome process ----------------------------------------------
    def is_running(self) -> bool:
        try:
            return httpx.get(f"{self.endpoint}/json/version", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            return False

    def launch_args(self, url: str | None = None) -> list[str]:
        args = [self.chrome_path, f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile_dir}", "--no-first-run", "--no-default-browser-check"]
        if url:
            args.append(url)
        return args

    def ensure_running(self, url: str | None = None) -> bool:
        """Launch Chrome unless something already answers on the port.

        Returns True if this call started it.
        """
        if self.is_running():
            return False
        if not Path(self.chrome_path).is_file():
            raise BrowserError(f"Chrome not found at {self.chrome_path} (Settings → Web Sessions)")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        log.info("Launching Chrome on port %d with profile %s", self.port, self.profile_dir)
        self._proc = subprocess.Popen(self.launch_args(url), close_fds=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.is_running():
                return True
            if self._proc.poll() is not None:
                break
            time.sleep(0.3)
        raise BrowserError(
            f"Chrome did not open its debugging port {self.port}. If Chrome is already open with "
            "this profile without the port, close it and launch again from Web Sessions.")

    # ---- per-site work -------------------------------------------------
    def site_lock(self, site: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(site, threading.Lock())

    def _worker(self, site: str) -> _SiteWorker:
        with self._guard:
            w = self._workers.get(site)
            if w is None or not w.thread.is_alive():
                w = self._workers[site] = _SiteWorker(self, site)
            return w

    def run(self, site: str, fn: Callable[[Any], Any], timeout: float | None = None) -> Any:
        """Run ``fn(page)`` on the site's worker thread and return its result."""
        return self._worker(site).submit(fn).result(timeout)

    def open_site(self, site: str) -> None:
        """Launch Chrome if needed, open the site's tab and bring it to the front."""
        home = SITES[site][0]
        self.ensure_running(home)
        self.run(site, lambda page: bring_to_front(page), timeout=90)

    def bring_to_front(self, site: str) -> None:
        try:
            self.run(site, bring_to_front, timeout=20)
        except Exception:  # noqa: BLE001 - best effort
            log.debug("bring_to_front failed", exc_info=True)

    def close(self) -> None:
        with self._guard:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()


def bring_to_front(page) -> None:
    """Un-minimise the Chrome window and focus the tab (runs on the site thread)."""
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds",
                 {"windowId": win["windowId"], "bounds": {"windowState": "normal"}})
        cdp.detach()
    except Exception:  # noqa: BLE001 - some window managers refuse; focusing the tab still helps
        log.debug("setWindowBounds failed", exc_info=True)
    page.bring_to_front()


_session: BrowserSession | None = None
_session_guard = threading.Lock()


def session() -> BrowserSession:
    """Process-wide browser session (created on first use)."""
    global _session
    with _session_guard:
        if _session is None:
            _session = BrowserSession()
        return _session
