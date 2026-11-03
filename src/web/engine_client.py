"""Client for the shared Flow engine (``mcp/google-flow/src/engine``).

The engine is one local process per data folder, found through ``engine.json``. It owns
Chrome, the queue and pacing, and outlives the app, so an agent's run keeps going and shows
up here later. Calls go over ``POST /rpc``; live progress comes from ``GET /events`` (SSE).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import httpx

from src.gen.models import JobStatus
from src.gen.progress import parse_ts

log = logging.getLogger(__name__)

START_TIMEOUT = 20.0
READ_TIMEOUT = 20.0  # the engine pings every 15 s, so silence this long means a dead stream


class EngineError(Exception):
    """The engine could not be started or reached."""


class EngineToolError(Exception):
    """A tool came back failed. ``payload`` holds ``error_code``, ``message``, ``retryable``..."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = payload or {}

    @property
    def code(self) -> str:
        return str(self.payload.get("error_code") or "")


class EngineClient:
    def __init__(self, data_dir: Path, command: list[str] | None = None, cwd: Path | None = None,
                 env: dict[str, str] | None = None, version: str = ""):
        self.data_dir = Path(data_dir)
        self.command, self.cwd, self.env, self.version = command, cwd, env, version
        self._lock = threading.Lock()
        self.on_launch = None  # callable(lock), told when this client has just started the engine

    # ---- finding or starting the engine ------------------------------
    def _read_lock(self) -> dict[str, Any] | None:
        try:
            return json.loads((self.data_dir / "engine.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _headers(lock: dict[str, Any]) -> dict[str, str]:
        return {"authorization": f"Bearer {lock['token']}"}

    @staticmethod
    def _url(lock: dict[str, Any]) -> str:
        return f"http://127.0.0.1:{lock['port']}"

    def _health(self, lock: dict[str, Any]) -> dict[str, Any] | None:
        """The health reply, or None when nothing listens. Raises on a live engine not answering."""
        try:
            reply = httpx.get(f"{self._url(lock)}/health", headers=self._headers(lock), timeout=2.0)
        except httpx.ConnectError:
            return None
        except httpx.HTTPError:
            # It may be mid-job, and a second engine on one Chrome could spend twice.
            raise EngineError(f"The Flow engine (pid {lock.get('pid')}) is alive but not answering. "
                              "Try again shortly.") from None
        return reply.json() if reply.status_code == 200 else None

    def ensure(self) -> dict[str, Any]:
        """The running engine's lock record, starting the engine if there is none."""
        with self._lock:
            lock = self._read_lock()
            health = self._health(lock) if lock else None
            if health and health.get("ready"):
                if not self.version or lock.get("version") == self.version:
                    return lock
                self._retire(lock)
            return self._launch()

    def _retire(self, lock: dict[str, Any]) -> None:
        reply = httpx.post(f"{self._url(lock)}/shutdown", headers=self._headers(lock), timeout=2.0)
        if reply.status_code == 409:
            raise EngineError("The Flow engine is running a job and needs an update. "
                              "Try again when the job has finished.")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self._health(lock):
            time.sleep(0.1)

    def _launch(self) -> dict[str, Any]:
        if not self.command:
            raise EngineError("The Flow engine is not running")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        error_file = self.data_dir / "engine-error.json"
        error_file.unlink(missing_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(self.command, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as exc:
            raise EngineError(f"Could not start the Flow engine ({self.command[0]}): {exc}") from None
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            lock = self._read_lock()
            if lock:
                health = self._health(lock)
                if health and health.get("ready") and (not self.version or lock.get("version") == self.version):
                    if self.on_launch:
                        self.on_launch(lock)
                    return lock
            if error_file.exists():
                raise EngineError(json.loads(error_file.read_text(encoding="utf-8")).get("message", "start failed"))
            time.sleep(0.1)
        raise EngineError(f"The Flow engine did not start. See the logs in {self.data_dir / 'logs'}.")

    # ---- calls -------------------------------------------------------
    def head(self) -> int:
        """The newest event number, to follow from before submitting a job."""
        lock = self.ensure()
        return int((self._health(lock) or {}).get("seq", 0))

    def call(self, tool: str, args: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
        """Call a tool; the result on success, ``EngineToolError`` on a failed one."""
        for attempt in (1, 2):
            lock = self.ensure()
            try:
                reply = httpx.post(f"{self._url(lock)}/rpc", headers=self._headers(lock),
                                   json={"tool": tool, "args": args or {}}, timeout=timeout)
            except httpx.ConnectError as exc:  # never reached it, so a repeat can't spend twice
                if attempt == 2:
                    raise EngineError(f"Could not reach the Flow engine: {exc}") from None
                continue
            except httpx.TimeoutException:
                raise TimeoutError(f"{tool} did not answer in {timeout:.0f} s") from None
            if reply.status_code == 401 and attempt == 1:
                continue  # the engine restarted with a new token between the two reads
            if reply.status_code != 200:
                raise EngineError(f"The Flow engine answered {reply.status_code}")
            body = reply.json()
            if body.get("ok"):
                return body.get("result") or {}
            raise EngineToolError(str(body.get("message") or "tool error"), body)
        raise AssertionError("unreachable")

    def events(self, since: int = 0, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        """Engine events after ``since``, for as long as ``stop`` is unset, reconnecting from the
        last one seen. A restarted engine sends ``{"type": "reset"}`` and numbers start over."""
        stop = stop or threading.Event()
        last = since
        while not stop.is_set():
            try:
                lock = self._read_lock()
                if lock is None:
                    raise httpx.ConnectError("no engine")
                timeout = httpx.Timeout(5.0, read=READ_TIMEOUT)
                with httpx.stream("GET", f"{self._url(lock)}/events", params={"since": last},
                                  headers=self._headers(lock), timeout=timeout) as stream:
                    name = ""
                    for line in stream.iter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("event: "):
                            name = line[7:]
                        elif line.startswith("data: "):
                            if name == "reset":
                                last = 0
                                yield {"type": "reset"}
                            else:
                                event = json.loads(line[6:])
                                last = int(event.get("seq", last))
                                yield event
                            name = ""
            except httpx.HTTPError:
                log.debug("Engine event stream lost; reconnecting", exc_info=True)
            stop.wait(1.0)


# ---- what the engine left on disk (needs no running engine) ------------
def read_manifests(data_dir: Path) -> list[dict[str, Any]]:
    """Every run's manifest, oldest first, from the engine's run registry."""
    runs = []
    try:
        lines = (Path(data_dir) / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return runs
    for line in lines:
        try:
            record = json.loads(line)
            runs.append(json.loads((Path(record["dir"]) / "manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            continue  # a moved run folder or a torn line must not hide the others
    return runs


def row_state(job: dict[str, Any]) -> dict[str, Any]:
    """A manifest job as app row fields: status, progress, outputs, error."""
    state = job.get("state")
    data = job.get("data") or {}
    status = {"done": JobStatus.DONE, "failed": JobStatus.FAILED, "cancelled": JobStatus.STOPPED,
              "needs_user": JobStatus.STOPPED, "paused": JobStatus.STOPPED,
              "queued": JobStatus.QUEUED}.get(state, JobStatus.RUNNING)
    outputs = [Path(o["file"]) for o in data.get("outputs") or [] if o.get("file")]
    live = status in (JobStatus.RUNNING, JobStatus.QUEUED)
    return {"status": status, "progress": 1.0 if status is JobStatus.DONE else 0.0, "outputs": outputs,
            "error": str((data.get("error") or {}).get("message") or ""),
            "stage": str(state or "") if live else "",
            # From the manifest, so the clock is right after an app restart.
            "started_at": parse_ts(job.get("submittedAt")) if live else None}


def uses_today(data_dir: Path) -> int:
    """Prompts the engine counted today against the daily cap."""
    try:
        state = json.loads((Path(data_dir) / "pacer.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(state.get("uses", 0)) if state.get("day") == date.today().isoformat() else 0
