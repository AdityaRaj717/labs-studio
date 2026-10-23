"""The google-flow MCP server as the app's Google Flow backend.

The app starts the MCP server (``node <web.flow_mcp_dir>/src/index.js``) as a
child process and calls its ``flow_generate_image`` tool for every job. The MCP
drives Flow in the Chrome the app launched (same CDP port), so the user's one
signed-in profile is shared. Jobs go to the Flow project the MCP keeps for the
``web.flow_campaign`` campaign.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from src.web.mcp_client import McpStdioClient, McpToolError

log = logging.getLogger(__name__)


def _settings():
    from src import config

    return config.settings()


class FlowMcp:
    def __init__(self, store=None, session=None, client_factory=McpStdioClient):
        self.store = store if store is not None else _settings()
        self._session = session
        self.client_factory = client_factory
        self.client: McpStdioClient | None = None
        self._connected = False
        self._lock = threading.Lock()

    @property
    def session(self):
        if self._session is None:
            from src.web.session import session

            self._session = session()
        return self._session

    @property
    def mcp_dir(self) -> Path:
        return Path(self.store.get("web.flow_mcp_dir", r"D:\Tools\google-flow-browser-mcp"))

    def command(self) -> list[str]:
        node = str(self.store.get("web.node_path", "node") or "node")
        return [node, str(self.mcp_dir / "src" / "index.js")]

    # ---- lifecycle ---------------------------------------------------
    def ensure(self) -> McpStdioClient:
        """Start the server if needed, make sure Chrome is up, connect once."""
        with self._lock:
            if self.client is None or not self.client.is_alive():
                self.client = self.client_factory(
                    self.command(), cwd=self.mcp_dir, name="google-flow",
                    stderr_path=Path(self.store.get("web.diag_dir", r"D:\glabs_web\diag")).parent
                    / "flow-mcp-stderr.log")
                self.client.start()
                self._connected = False
            if not self._connected:
                # Launch the app's Chrome (dedicated profile, CDP port) so the MCP attaches
                # to it instead of starting a browser with its own profile.
                self.session.ensure_running(self.store.get("web.flow_home", "https://flow.google.com/"))
                res = self.client.call_tool("flow_connect", {"open_flow": False}, timeout=120)
                log.info("Flow MCP connected: %s", res.get("status"))
                self._connected = True
            return self.client

    def close(self) -> None:
        with self._lock:
            if self.client is not None:
                self.client.close()
            self.client = None
            self._connected = False

    # ---- tools -----------------------------------------------------------
    def generate_image(self, args: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Call ``flow_generate_image`` (generating, not just preparing) and wait for it."""
        full = {
            "auto_confirm": True,
            "campaign": self.store.get("web.flow_campaign", "labs-studio"),
            "project_name": "Labs Studio",
            "wait_ms": int((timeout + 120) * 1000),
            "timeout_ms": int(timeout * 1000),
            **args,
        }
        for attempt in (1, 2):
            client = self.ensure()
            try:
                return client.call_tool("flow_generate_image", full, timeout=timeout + 240)
            except McpToolError as exc:
                if exc.code == "BROWSER_NOT_CONNECTED" and attempt == 1:
                    self._connected = False  # Chrome restarted: connect again and retry once
                    continue
                raise
        raise AssertionError("unreachable")

    def status(self) -> dict[str, Any]:
        return self.ensure().call_tool("flow_status", {}, timeout=60)


_flow_mcp: FlowMcp | None = None
_guard = threading.Lock()


def flow_mcp() -> FlowMcp:
    global _flow_mcp
    with _guard:
        if _flow_mcp is None:
            _flow_mcp = FlowMcp()
        return _flow_mcp
