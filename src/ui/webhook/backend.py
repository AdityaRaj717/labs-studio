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
GENERATOR_PAGES = ("flow_image", "flow_video")

GUI_TIMEOUT = 15.0


def job_info(page_key: str, job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "page": page_key,
        "index": job.index,
        "prompt": job.prompt,
        "status": job.status.value,
        "progress": round(job.progress, 3),
        "progress_source": job.progress_source,
        "stage": job.stage,
        "attempts": job.attempts,
        "error": job.error,
        "outputs": [str(p) for p in job.outputs],
        "refs": [str(p) for p in job.refs],
        "character": job.character,
        "characters": [job.character, *job.cast] if job.character else list(job.cast),
        "scenes": list(job.scenes),
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

    def _project(self, key: str):
        """Make ``key`` (name or id) the active project; "" keeps the active one.

        Returns the project, or None when projects are off.
        """
        from src import projects
        from src.projects import ProjectBusyError

        store = projects.store()
        if store is None:
            if key:
                raise ApiError(400, "projects are not enabled in this app")
            return None
        if not key:
            return store.active
        project = store.find(key)
        if project is None:
            names = ", ".join(p.name for p in store.list())
            raise ApiError(404, f"unknown project {key!r}; use one of: {names}")
        try:
            store.activate(project.id)
        except ProjectBusyError as exc:
            raise ApiError(409, f"can't switch to project {project.name!r}: {exc}") from None
        return project

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

    @staticmethod
    def _lookup(store, names: list[str], kind: str) -> list[str]:
        """Library ids for names; an unknown name is a 400 that lists the known ones."""
        ids = []
        for name in names:
            entry = store.by_name(name)
            if entry is None:
                known = ", ".join(e.name for e in store.all()) or "none yet"
                raise ApiError(400, f"no {kind} named {name!r} (known: {known})")
            ids.append(entry.id)
        return ids

    def submit(self, req: dict) -> dict:
        refs = [Path(r) for r in req.get("refs", [])]
        missing = [str(r) for r in refs if not r.is_file()]
        if missing:
            raise ApiError(400, f"reference file(s) not found: {', '.join(missing)}")

        def add() -> dict:
            project = self._project(req.get("project", ""))
            page = self._page(req["page"])
            names = req.get("characters") or ([req["character"]] if req.get("character") else [])
            chars = self._lookup(page.characters, names, "character")
            scenes = self._lookup(page.scenes, req.get("scenes") or [], "scene") if req.get("scenes") else []
            jobs = page.add_prompts(req["prompts"])
            if chars or scenes or refs:
                from src.characters import attach
                for job in jobs:
                    for r in refs:
                        if r not in job.refs:
                            job.refs.append(r)
                    if chars:
                        attach.set_characters(job, chars, page.characters)
                    if scenes:
                        attach.set_scenes(job, scenes, page.scenes)
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
            out = {"page": req["page"], "started": started,
                   "jobs": [job_info(req["page"], j) for j in jobs]}
            if project is not None:
                out["project"] = project.name
            return out

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
