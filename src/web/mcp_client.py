"""Minimal MCP client over stdio (newline-delimited JSON-RPC 2.0).

Enough for the app to start an MCP server as a child process, do the
``initialize`` handshake and call tools. Tool results are expected as one text
content block holding JSON, which is what the google-flow MCP returns.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"


class McpError(Exception):
    """The server could not be started or reached, or broke the protocol."""


class McpToolError(Exception):
    """A tool call came back with ``isError``. ``payload`` is its parsed JSON, if any."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = payload or {}

    @property
    def code(self) -> str:
        return str(self.payload.get("error_code") or "")


def tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    """The JSON object inside a ``tools/call`` result (first text block)."""
    for block in result.get("content") or []:
        if block.get("type") == "text":
            try:
                data = json.loads(block.get("text") or "")
            except ValueError:
                return {"text": block.get("text") or ""}
            return data if isinstance(data, dict) else {"value": data}
    return {}


class McpStdioClient:
    def __init__(self, command: list[str], cwd: str | Path | None = None,
                 stderr_path: str | Path | None = None, name: str = "mcp"):
        self.command = command
        self.cwd = str(cwd) if cwd else None
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.name = name
        self.proc: subprocess.Popen | None = None
        self._next_id = 1
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.server_info: dict[str, Any] = {}

    # ---- lifecycle ---------------------------------------------------
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout: float = 30) -> None:
        if self.is_alive():
            return
        stderr = subprocess.DEVNULL
        if self.stderr_path:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr = open(self.stderr_path, "ab")  # noqa: SIM115 - lives as long as the process
        try:
            self.proc = subprocess.Popen(
                self.command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            raise McpError(f"Could not start {self.name} ({' '.join(self.command)}): {exc}") from None
        threading.Thread(target=self._read_loop, name=f"{self.name}-reader", daemon=True).start()
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "labs-studio", "version": "0.1.0"},
        }, timeout=timeout)
        self.server_info = result.get("serverInfo") or {}
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        log.info("MCP server %s started: %s", self.name, self.server_info)

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(5)
        except Exception:  # noqa: BLE001
            proc.kill()
        self._fail_all(McpError(f"{self.name} closed"))

    # ---- calls ---------------------------------------------------------
    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float | None = 60) -> dict[str, Any]:
        if not self.is_alive():
            raise McpError(f"{self.name} is not running")
        fut: Future = Future()
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            self._pending[rid] = fut
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        try:
            return fut.result(timeout)
        finally:
            with self._lock:
                self._pending.pop(rid, None)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None,
                  timeout: float | None = 60) -> dict[str, Any]:
        """Call a tool and return its JSON payload; raise McpToolError on ``isError``."""
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout)
        payload = tool_payload(result)
        if result.get("isError"):
            raise McpToolError(str(payload.get("message") or payload.get("text") or "tool error"), payload)
        return payload

    def list_tools(self) -> list[str]:
        return [t.get("name", "") for t in self.request("tools/list").get("tools", [])]

    # ---- plumbing -------------------------------------------------------
    def _send(self, msg: dict[str, Any]) -> None:
        data = (json.dumps(msg) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, AttributeError) as exc:
                raise McpError(f"{self.name} pipe closed: {exc}") from None

    def _read_loop(self) -> None:
        proc = self.proc
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                log.debug("%s: non-JSON line on stdout: %s", self.name, line[:200])
                continue
            rid = msg.get("id")
            if rid is None or "method" in msg:
                continue  # notifications / server requests: not used here
            with self._lock:
                fut = self._pending.get(rid)
            if fut is None or fut.done():
                continue
            if "error" in msg:
                err = msg["error"] or {}
                fut.set_exception(McpError(f"{self.name}: {err.get('message', err)}"))
            else:
                fut.set_result(msg.get("result") or {})
        self._fail_all(McpError(f"{self.name} exited (code {proc.poll()})"))

    def _fail_all(self, exc: Exception) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for fut in pending:
            if not fut.done():
                fut.set_exception(exc)
