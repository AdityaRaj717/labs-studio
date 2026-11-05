"""The Flow Chrome, as the app sees it: the engine owns the browser, so these are engine calls."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class BrowserSession:
    def __init__(self, backend=None):
        self._backend = backend

    @property
    def backend(self):
        if self._backend is None:
            from src.web.flow_mcp import flow_mcp

            self._backend = flow_mcp()
        return self._backend

    def login_state(self, site: str = "flow", open_flow: bool = False) -> str:
        """``ok`` or ``login``, from the engine's look at the account."""
        res = self.backend.call_tool("flow_connect", {"open_flow": open_flow}, 120)
        return "login" if res.get("status") == "oauth_required" or res.get("accountStatus") == "mismatch" else "ok"

    def open_site(self, site: str = "flow") -> str:
        """Launch Chrome if needed, open Flow and bring it to the front; the login state."""
        state = self.login_state(site, open_flow=True)
        self.bring_to_front(site)
        return state

    def bring_to_front(self, site: str = "flow") -> None:
        try:
            self.backend.call_tool("flow_bring_to_front", {}, 20)
        except Exception:  # noqa: BLE001 - best effort
            log.debug("bring_to_front failed", exc_info=True)


_session: BrowserSession | None = None
_session_guard = threading.Lock()


def session() -> BrowserSession:
    """Process-wide browser session (created on first use)."""
    global _session
    with _session_guard:
        if _session is None:
            _session = BrowserSession()
        return _session
