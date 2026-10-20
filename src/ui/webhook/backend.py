"""Webhook backend: turns API calls into rows on the app's generator pages.

The HTTP server calls this from its own threads. Anything that touches a page
(building it, adding rows, starting the queue) is run on the GUI thread via a
queued signal; job status is read straight from the ``Job`` objects.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from src.gen.models import Job
from src.webhook.server import ApiError

log = logging.getLogger(__name__)

# Pages the API may submit to, in the order GET /api/pages lists them.
# "demo" is a hidden page on the offline FakeProvider (no key, no network).
GENERATOR_PAGES = ("flow_image", "flow_video", "grok", "openai_image", "demo")

GUI_TIMEOUT = 15.0


def job_info(page_key: str, job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "page": page_key,
        "index": job.index,
        "prompt": job.prompt,
        "status": job.status.value,
        "progress": round(job.progress, 3),
        "attempts": job.attempts,
        "error": job.error,
        "outputs": [str(p) for p in job.outputs],
        "refs": [str(p) for p in job.refs],
        "character": job.character,
    }


class PageBackend(QObject):
    """``src.webhook.server.Backend`` over the app's generator pages."""

    _invoke = Signal(object)
    jobs_submitted = Signal(str, int)  # page key, job count (GUI thread)

    def __init__(self, page_lookup: Callable[[str], Any], stats=None,
                 page_keys: tuple[str, ...] = GENERATOR_PAGES, parent: QObject | None = None):
        super().__init__(parent)
        self.page_lookup = page_lookup
        self.stats_store = stats
        self.page_keys = tuple(page_keys)
        self._lock = threading.Lock()
        self._jobs: dict[int, tuple[str, Job]] = {}
        self._invoke.connect(self._run_call)

    # ---- GUI-thread marshalling -------------------------------------
    def _run_call(self, call) -> None:
        call()

    def on_gui(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` on the GUI thread and return its result (or re-raise)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        done = threading.Event()
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
                box["error"] = exc
            finally:
                done.set()

        self._invoke.emit(call)
        if not done.wait(GUI_TIMEOUT):
            raise ApiError(503, "the app did not respond in time (is a dialog open?)")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # ---- Backend API -------------------------------------------------
    def _page(self, key: str):
        if key not in self.page_keys:
            raise ApiError(404, f"unknown page {key!r}; use one of: {', '.join(self.page_keys)}")
        page = self.page_lookup(key)
        if not hasattr(page, "add_prompts") or not hasattr(page, "queue"):
            raise ApiError(409, f"page {key!r} is not a generator page")
        return page

    def pages(self) -> list[dict]:
        def build() -> list[dict]:
            out = []
            for key in self.page_keys:
                try:
                    page = self._page(key)
                except (ApiError, KeyError):
                    continue
                out.append({"key": key, "provider": page.provider.key, "name": page.provider.name,
                            "running": page.queue.is_running()})
            return out
        return self.on_gui(build)

    def submit(self, req: dict) -> dict:
        refs = [Path(r) for r in req.get("refs", [])]
        missing = [str(r) for r in refs if not r.is_file()]
        if missing:
            raise ApiError(400, f"reference file(s) not found: {', '.join(missing)}")

        def add() -> dict:
            page = self._page(req["page"])
            char = None
            if req.get("character"):
                char = page.characters.by_name(req["character"])
                if char is None:
                    raise ApiError(400, f"no character named {req['character']!r}")
            jobs = page.add_prompts(req["prompts"])
            if char is not None or refs:
                from src.characters import attach
                for job in jobs:
                    for r in refs:
                        if r not in job.refs:
                            job.refs.append(r)
                    if char is not None:
                        attach.attach(job, char.id, page.characters)
                    page.model.refresh_job(job.id)
            with self._lock:
                for job in jobs:
                    self._jobs[job.id] = (req["page"], job)
            started = False
            if req.get("start", True):
                if page.queue.is_running():
                    started = page.queue.retry(jobs) > 0
                else:
                    started = page.start() > 0
            self.jobs_submitted.emit(req["page"], len(jobs))
            log.info("Webhook: %d job(s) added to %s%s", len(jobs), req["page"],
                     " and started" if started else "")
            return {"page": req["page"], "started": started,
                    "jobs": [job_info(req["page"], j) for j in jobs]}

        return self.on_gui(add)

    def job(self, job_id: int) -> dict | None:
        with self._lock:
            entry = self._jobs.get(job_id)
        return job_info(*entry) if entry else None

    def jobs(self, page: str | None = None) -> list[dict]:
        with self._lock:
            entries = list(self._jobs.values())
        return [job_info(k, j) for k, j in entries if page in (None, k)]

    def stats(self) -> dict:
        if self.stats_store is None:
            return {"since": "", "providers": [], "totals": {}}
        return self.stats_store.snapshot()
