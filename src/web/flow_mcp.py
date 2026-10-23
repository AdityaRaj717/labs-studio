"""The google-flow MCP server as the app's Google Flow backend.

The app starts the MCP server (``node <web.flow_mcp_dir>/src/index.js``) as a
child process and calls its ``flow_generate_image`` tool for every job. The MCP
drives Flow in the Chrome the app launched (same CDP port), so the user's one
signed-in profile is shared. Each app project (``src.projects``) has its own Flow
project: ``ensure_project`` opens it (creating and titling it when missing) and
jobs pass its URL. Without projects, jobs go to the ``web.flow_campaign`` project.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from src.web.mcp_client import McpStdioClient, McpToolError

log = logging.getLogger(__name__)

BUNDLED_MCP_DIR = Path(__file__).resolve().parents[2] / "mcp" / "google-flow"
OLD_MCP_DIR = Path(r"D:\Tools\google-flow-browser-mcp")  # phase 11a default, now the repo copy


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
        self._project_lock = threading.Lock()
        self._opened: tuple[str, str, str] | None = None  # (project id, url, title) open in the tab

    @property
    def session(self):
        if self._session is None:
            from src.web.session import session

            self._session = session()
        return self._session

    @property
    def mcp_dir(self) -> Path:
        value = self.store.get("web.flow_mcp_dir", "") or ""
        if not value or Path(value) == OLD_MCP_DIR:
            return BUNDLED_MCP_DIR
        return Path(value)

    @property
    def data_dir(self) -> Path:
        """Where the MCP writes logs, screenshots and its project list."""
        return Path(self.store.get("web.diag_dir", r"D:\glabs_web\diag")).parent / "flow-mcp"

    def command(self) -> list[str]:
        node = str(self.store.get("web.node_path", "node") or "node")
        return [node, str(self.mcp_dir / "src" / "index.js")]

    def env(self) -> dict[str, str]:
        """The app's Chrome settings, so the MCP attaches to the same browser."""
        env = dict(os.environ)
        env.update({
            "FLOW_CDP_PORT": str(self.store.get("web.port", 9333)),
            "FLOW_CHROME_PATH": str(self.store.get("web.chrome_path", "")),
            "FLOW_CHROME_PROFILE_DIR": str(self.store.get("web.profile_dir", "")),
            "FLOW_DATA_DIR": str(self.data_dir),
        })
        return {k: v for k, v in env.items() if v}

    # ---- lifecycle ---------------------------------------------------
    def ensure(self) -> McpStdioClient:
        """Start the server if needed, make sure Chrome is up, connect once."""
        with self._lock:
            if self.client is None or not self.client.is_alive():
                self.client = self.client_factory(
                    self.command(), cwd=self.mcp_dir, name="google-flow", env=self.env(),
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
            self._opened = None

    # ---- tools -----------------------------------------------------------
    def _call(self, tool: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
        for attempt in (1, 2):
            client = self.ensure()
            try:
                return client.call_tool(tool, args, timeout=timeout)
            except McpToolError as exc:
                if exc.code == "BROWSER_NOT_CONNECTED" and attempt == 1:
                    self._connected = False  # Chrome restarted: connect again and retry once
                    self._opened = None
                    continue
                raise
        raise AssertionError("unreachable")

    def open_project(self, name: str, url: str = "", create: bool = True) -> dict[str, Any]:
        """``flow_open_project``: open ``url`` (or create a project) titled ``name``."""
        args = {"name": name, "create_if_missing": create}
        if url:
            args["url"] = url
        return self._call("flow_open_project", args, timeout=180)

    def ensure_project(self, project, force: bool = False) -> str:
        """Open ``project``'s Flow project in the tab, creating it if missing; return its URL."""
        with self._project_lock:
            if not force and self._opened == (project.id, project.flow_url, project.name) and project.flow_url:
                return project.flow_url
            res = self.open_project(project.name, project.flow_url)
            url = res.get("url", "")
            if not url:
                raise McpToolError("flow_open_project returned no URL", {"error_code": "UNKNOWN_UI_CHANGE"})
            if res.get("created"):
                log.info("Created Flow project %r: %s", project.name, url)
            if url != project.flow_url or res.get("title", "") != project.flow_title:
                project.set_flow(url, res.get("title", ""))
            self._opened = (project.id, url, project.name)
            return url

    def generate_image(self, args: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Call ``flow_generate_image`` (generating, not just preparing) and wait for it.

        With projects installed the job goes to the active project's Flow project.
        """
        from src import projects

        full = {
            "auto_confirm": True,
            "campaign": self.store.get("web.flow_campaign", "labs-studio"),
            "project_name": "Labs Studio",
            "wait_ms": int((timeout + 120) * 1000),
            "timeout_ms": int(timeout * 1000),
            **args,
        }
        project = projects.current()
        for attempt in (1, 2):
            if project is not None:
                full["project_url"] = self.ensure_project(project)
            try:
                return self._call("flow_generate_image", full, timeout=timeout + 240)
            except McpToolError as exc:
                if exc.code == "PROJECT_NOT_FOUND" and project is not None and attempt == 1:
                    self._opened = None  # deleted in Flow meanwhile: make a new one and retry
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


def open_project_async(project) -> threading.Thread:
    """Open ``project``'s Flow project in the background (on switch, or from the Projects page)."""
    def run() -> None:
        try:
            url = flow_mcp().ensure_project(project)
            log.info("Flow project for %r: %s", project.name, url)
        except Exception as exc:  # noqa: BLE001 - shown in the log; the next Flow job retries
            log.warning("Could not open the Flow project for %r: %s", project.name, exc)

    thread = threading.Thread(target=run, name="flow-open-project", daemon=True)
    thread.start()
    return thread
