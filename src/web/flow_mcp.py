"""The shared Flow engine as the app's Google Flow backend.

The engine (``src.web.engine_client``) owns Chrome, the queue and pacing. Each app project
(``src.projects``) has its own Flow project: ``ensure_project`` opens it (creating and titling
it when missing) and jobs pass its URL.

Phase 14b: library characters and scenes (``src.characters``) are set up in the Flow project
before a job that uses them (``src.characters.flow_sync``), and when a project becomes active
(``sync_project``). Jobs then pass them by Flow name.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from src.gen.provider import StopRequested
from src.web.engine_client import EngineClient, EngineToolError

log = logging.getLogger(__name__)

BUNDLED_MCP_DIR = Path(__file__).resolve().parents[2] / "mcp" / "google-flow"
OLD_MCP_DIR = Path(r"D:\Tools\google-flow-browser-mcp")  # phase 11a default, now the repo copy


WAIT_MS = 2000  # flow_wait slice: how quickly Stop is noticed


def _settings():
    from src import config

    return config.settings()


class FlowMcp:
    def __init__(self, store=None, client_factory=EngineClient):
        self.store = store if store is not None else _settings()
        self.client_factory = client_factory
        self._client = None
        self._lock = threading.Lock()
        self._project_lock = threading.Lock()
        self._opened: tuple[str, str, str] | None = None  # (project id, url, title) open in the tab
        self._sync = None

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
        return [node, str(self.mcp_dir / "src" / "engine" / "start.js")]

    def env(self) -> dict[str, str]:
        """The Chrome settings the engine launches or attaches with."""
        env = dict(os.environ)
        env.update({
            "FLOW_CDP_PORT": str(self.store.get("web.port", 9333)),
            "FLOW_CHROME_PATH": str(self.store.get("web.chrome_path", "")),
            "FLOW_CHROME_PROFILE_DIR": str(self.store.get("web.profile_dir", "")),
            "FLOW_DATA_DIR": str(self.data_dir),
            "FFMPEG_PATH": str(self.store.get("tools.ffmpeg_path", "") or ""),
        })
        return {k: v for k, v in env.items() if v}

    # ---- lifecycle ---------------------------------------------------
    @property
    def client(self):
        with self._lock:
            if self._client is None:
                try:
                    version = json.loads((self.mcp_dir / "package.json").read_text(encoding="utf-8"))["version"]
                except (OSError, ValueError, KeyError):
                    version = ""
                self._client = self.client_factory(self.data_dir, self.command(), self.mcp_dir, self.env(), version)
                self._client.on_launch = self._push_keys
            return self._client

    def _push_keys(self, lock: dict[str, Any]) -> None:
        from src.keys_push import pushKeys

        try:
            pushKeys(self._client, lock=lock)
        except Exception as exc:  # noqa: BLE001 - audio tools then answer MISSING_API_KEY; Flow work is unaffected
            log.info("No audio keys sent to the engine: %s", type(exc).__name__)

    def close(self) -> None:
        """Forget the engine connection. The engine keeps running, with any job it has."""
        with self._lock:
            self._client = None
            self._opened = None

    # ---- tools -----------------------------------------------------------
    def call_tool(self, tool: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self.client.call(tool, args, timeout)

    def push_pacing(self) -> None:
        """Hand the Web Sessions daily cap and gap to the engine, which does the pacing."""
        lo, hi = sorted((float(self.store.get("web.gap_min", 0) or 0), float(self.store.get("web.gap_max", 0) or 0)))
        self.call_tool("flow_set_pacing", {"dailyCap": int(self.store.get("web.caps.flow", 0) or 0),
                                           "minGapMs": int(lo * 1000), "maxGapMs": int(hi * 1000)}, 10)

    @property
    def sync(self):
        """The ``FlowSync`` over the app-wide character and scene libraries."""
        if self._sync is None:
            from src.characters.flow_sync import FlowSync
            from src.characters.store import default_store, scene_store

            self._sync = FlowSync(self.call_tool, default_store(), scene_store())
        return self._sync

    def sync_project(self, project) -> dict[str, Any]:
        """Set up every character and scene the project's prompt rows use in its Flow project."""
        from src.characters.flow_sync import used_in_rows

        url = self.ensure_project(project)
        chars, scenes = used_in_rows(project.all_rows())
        if not chars and not scenes:
            return {"characters": {}, "scenes": {}, "errors": []}
        return self.sync.sync(url, chars, scenes)

    def open_project(self, name: str, url: str = "", create: bool = True) -> dict[str, Any]:
        """``flow_open_project``: open ``url`` (or create a project) titled ``name``."""
        args = {"name": name, "create_if_missing": create}
        if url:
            args["url"] = url
        return self.call_tool("flow_open_project", args, 180)

    def ensure_project(self, project, force: bool = False) -> str:
        """Open ``project``'s Flow project in the tab, creating it if missing; return its URL."""
        with self._project_lock:
            if not force and self._opened == (project.id, project.flow_url, project.name) and project.flow_url:
                return project.flow_url
            res = self.open_project(project.name, project.flow_url)
            url = res.get("url", "")
            if not url:
                raise EngineToolError("flow_open_project returned no URL", {"error_code": "UNKNOWN_UI_CHANGE"})
            if res.get("created"):
                log.info("Created Flow project %r: %s", project.name, url)
            if url != project.flow_url or res.get("title", "") != project.flow_title:
                project.set_flow(url, res.get("title", ""))
            self._opened = (project.id, url, project.name)
            return url

    def run_job(self, tool: str, args: dict[str, Any], timeout: float, characters: list[str] | None = None,
                scenes: list[str] | None = None, on_event: Callable[[dict], None] | None = None,
                should_stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        """Queue a generation and wait for it; its final job view (``outputs``...).

        ``characters`` / ``scenes`` are library ids: they are set up in the active project's
        Flow project first if needed and passed by their Flow names. ``idempotency_key`` in
        ``args`` makes a repeat return the first job instead of spending again.
        """
        from src import projects

        project = projects.current()
        self.push_pacing()
        key = args.get("idempotency_key", "")
        for attempt in (1, 2):
            full = {"auto_confirm": True, **args}
            if project is None:
                full.setdefault("project_name", "Labs Studio")
            else:
                full["project_url"] = self.ensure_project(project)
                full["output_root"] = str(project.output_dir)
            if characters or scenes:
                url = full.get("project_url") or self._campaign_url()
                names, places = self.sync.names(url, characters or [], scenes or [])
                full["ingredients"] = [*full.get("ingredients", []), *({"character": n} for n in names),
                                       *({"scene": n} for n in places)]
            if key and attempt == 2:
                full["idempotency_key"] = f"{key}:new-project"
            try:
                return self._follow(tool, full, timeout, on_event, should_stop)
            except EngineToolError as exc:
                if exc.code == "PROJECT_NOT_FOUND" and project is not None and attempt == 1:
                    self._opened = None  # deleted in Flow meanwhile: make a new one and retry
                    continue
                raise
        raise AssertionError("unreachable")

    def _follow(self, tool, args, timeout, on_event, should_stop) -> dict[str, Any]:
        client = self.client
        since = client.head()
        queued = client.call(tool, args, 60)
        job_id = queued.get("job_id")
        if not job_id:
            raise EngineToolError(f"{tool} queued nothing", {"error_code": "UNKNOWN_UI_CHANGE"})
        stop = threading.Event()

        def follow() -> None:
            for event in client.events(since, stop):
                if event.get("jobId") == job_id and on_event:
                    on_event(event)

        threading.Thread(target=follow, name="flow-events", daemon=True).start()
        deadline = time.monotonic() + timeout + 240
        try:
            while True:
                if should_stop():
                    client.call("flow_job_control", {"action": "cancel", "job_id": job_id}, 30)
                    raise StopRequested()
                view = client.call("flow_wait", {"job_id": job_id, "wait_ms": WAIT_MS}, 30)
                if view.get("finished"):
                    break
                if view.get("queue_paused"):
                    paused = view["queue_paused"]
                    raise EngineToolError(str(paused.get("next_action") or "The Flow queue is paused"),
                                          {"error_code": paused.get("reason")})
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Flow job {job_id} is still running after {timeout + 240:.0f} s")
        finally:
            stop.set()
        if view.get("state") == "done":
            return view
        if view.get("state") == "cancelled":
            raise StopRequested()
        error = view.get("error") or {"error_code": view.get("state"), "message": f"The job is {view.get('state')}"}
        raise EngineToolError(str(error.get("message") or "job failed"), error)

    def _campaign_url(self) -> str:
        """Without projects there is no URL to set characters up in."""
        raise EngineToolError("characters and scenes need an app project (Projects page)",
                              {"error_code": "INVALID_PARAMS"})

    def status(self) -> dict[str, Any]:
        return self.call_tool("flow_status", {}, 60)


_flow_mcp: FlowMcp | None = None
_guard = threading.Lock()


def flow_mcp() -> FlowMcp:
    global _flow_mcp
    with _guard:
        if _flow_mcp is None:
            _flow_mcp = FlowMcp()
        return _flow_mcp


def open_project_async(project, sync: bool = True) -> threading.Thread:
    """Open ``project``'s Flow project in the background (on switch, or from the Projects page),
    then set up the characters and scenes its prompts use (``sync``)."""
    def run() -> None:
        try:
            url = flow_mcp().ensure_project(project)
            log.info("Flow project for %r: %s", project.name, url)
            if sync:
                res = flow_mcp().sync_project(project)
                done = len(res["characters"]) + len(res["scenes"])
                if done or res["errors"]:
                    log.info("Flow characters/scenes for %r: %d ready, %d failed",
                             project.name, done, len(res["errors"]))
        except Exception as exc:  # noqa: BLE001 - shown in the log; the next Flow job retries
            log.warning("Could not open the Flow project for %r: %s", project.name, exc)

    thread = threading.Thread(target=run, name="flow-open-project", daemon=True)
    thread.start()
    return thread
