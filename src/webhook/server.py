"""Local HTTP API that feeds jobs into this app's own generator queues.

Qt-free. The server runs on its own thread; every request is handed to a
``Backend`` (see ``src.ui.webhook.backend`` for the one that talks to the
generator pages on the GUI thread).

Routes (JSON in, JSON out):
    GET  /api/health          app name, version, whether a token is required
    GET  /api/pages           page keys that accept jobs
    POST /api/jobs            submit: {"page", "prompt" | "prompts", "refs"?, "character"?, "start"?}
    GET  /api/jobs[?page=k]   jobs submitted over the API
    GET  /api/jobs/<id>       one job's status, progress, error and output paths
    GET  /api/stats           per-provider counts

When a token is set, every request needs ``Authorization: Bearer <token>``
(or ``X-Api-Token: <token>``), else 401.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlsplit

from src import APP_NAME, __version__

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 1024 * 1024  # 1 MB of JSON is plenty for prompt lists
MAX_PROMPTS = 1000


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Backend(Protocol):
    def pages(self) -> list[dict]: ...
    def submit(self, payload: dict) -> dict: ...
    def job(self, job_id: int) -> dict | None: ...
    def jobs(self, page: str | None = None) -> list[dict]: ...
    def stats(self) -> dict: ...


@dataclass
class RequestRecord:
    method: str
    path: str
    status: int
    client: str


def new_token() -> str:
    return secrets.token_urlsafe(24)


def parse_submit(payload: Any) -> dict:
    """Validate a POST /api/jobs body and normalise it.

    Returns ``{"page", "prompts", "refs", "character", "start"}``.
    """
    if not isinstance(payload, dict):
        raise ApiError(400, "body must be a JSON object")
    page = payload.get("page")
    if not isinstance(page, str) or not page:
        raise ApiError(400, "'page' is required (see GET /api/pages)")
    prompts = payload.get("prompts")
    if prompts is None and "prompt" in payload:
        prompts = [payload["prompt"]]
    if not isinstance(prompts, list) or not prompts:
        raise ApiError(400, "give 'prompt' (string) or 'prompts' (list of strings)")
    if len(prompts) > MAX_PROMPTS:
        raise ApiError(400, f"at most {MAX_PROMPTS} prompts per request")
    clean = []
    for p in prompts:
        if not isinstance(p, str) or not p.strip():
            raise ApiError(400, "every prompt must be a non-empty string")
        clean.append(p.strip())
    refs = payload.get("refs") or []
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise ApiError(400, "'refs' must be a list of file paths")
    character = payload.get("character") or ""
    if not isinstance(character, str):
        raise ApiError(400, "'character' must be a character name")
    start = payload.get("start", True)
    if not isinstance(start, bool):
        raise ApiError(400, "'start' must be true or false")
    return {"page": page, "prompts": clean, "refs": refs, "character": character, "start": start}


class _Handler(BaseHTTPRequestHandler):
    server: "_HTTPServer"
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME.replace(' ', '')}/{__version__}"

    # ---- plumbing ----------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - silence stderr logging
        log.debug("webhook %s - " + fmt, self.client_address[0], *args)

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        owner = self.server.owner
        owner._record(RequestRecord(self.command, self.path, status, self.client_address[0]))

    def _authorised(self) -> bool:
        token = self.server.owner.token
        if not token:
            return True
        given = self.headers.get("X-Api-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        return hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

    def _body(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if length > MAX_BODY:
            raise ApiError(413, "body too large")
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "body is not valid JSON") from None

    def _dispatch(self, method: str) -> None:
        try:
            if not self._authorised():
                # Drain the body so the connection stays usable.
                if method == "POST":
                    length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
                    self.rfile.read(length)
                raise ApiError(401, "missing or wrong API token")
            url = urlsplit(self.path)
            parts = [p for p in url.path.split("/") if p]
            query = parse_qs(url.query)
            self._send(*self._route(method, parts, query))
        except ApiError as exc:
            self._send(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 - never leave a client hanging
            log.exception("Webhook request failed")
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _route(self, method: str, parts: list[str], query: dict) -> tuple[int, Any]:
        backend = self.server.owner.backend
        if parts[:1] != ["api"]:
            raise ApiError(404, "not found (routes live under /api)")
        rest = parts[1:]
        if method == "GET" and rest == ["health"]:
            return 200, {"ok": True, "app": APP_NAME, "version": __version__,
                         "token_required": bool(self.server.owner.token)}
        if method == "GET" and rest == ["pages"]:
            return 200, {"pages": backend.pages()}
        if method == "GET" and rest == ["stats"]:
            return 200, backend.stats()
        if rest[:1] == ["jobs"]:
            if method == "POST" and len(rest) == 1:
                return 202, backend.submit(parse_submit(self._body()))
            if method == "GET" and len(rest) == 1:
                page = (query.get("page") or [None])[0]
                return 200, {"jobs": backend.jobs(page)}
            if method == "GET" and len(rest) == 2:
                try:
                    job_id = int(rest[1])
                except ValueError:
                    raise ApiError(400, "job id must be a number") from None
                info = backend.job(job_id)
                if info is None:
                    raise ApiError(404, f"no job {job_id} submitted over the API")
                return 200, info
        raise ApiError(405 if rest and rest[0] in ("jobs", "health", "pages", "stats") else 404,
                       f"{method} /{'/'.join(parts)} is not supported")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows reuse would let two servers share a port
    owner: "WebhookServer"


class WebhookServer:
    """Start/stop wrapper around a threaded ``http.server``."""

    def __init__(self, backend: Backend, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 token: str = "", on_request: Callable[[RequestRecord], None] | None = None):
        self.backend = backend
        self.host = host
        self.port = port
        self.token = token
        self.on_request = on_request or (lambda rec: None)
        self._httpd: _HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"

    def start(self) -> None:
        """Bind and serve. Raises ``OSError`` if the port is taken."""
        if self._httpd is not None:
            return
        httpd = _HTTPServer((self.host, int(self.port)), _Handler)
        httpd.owner = self
        self.port = httpd.server_address[1]  # resolves port 0 to the real one
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="webhook-server", daemon=True)
        self._thread.start()
        log.info("Webhook API listening on %s:%d (token %s)", self.host, self.port,
                 "required" if self.token else "off")

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        log.info("Webhook API stopped")

    def _record(self, rec: RequestRecord) -> None:
        try:
            self.on_request(rec)
        except Exception:  # noqa: BLE001
            log.exception("on_request callback failed")
