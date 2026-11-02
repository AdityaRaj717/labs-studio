"""Show what agents run on the shared engine as rows in the app.

The manifests are the truth, so a run made while the app was closed shows on the next start.
Engine events only say when to look again. Jobs the app started (key ``app:``) already have
their row, and a Production's (key ``prod:``) belong to its own review list.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from src.gen.models import Job
from src.projects.store import job_to_row, row_to_job
from src.web.engine_client import read_manifests, row_state

log = logging.getLogger(__name__)

SKIPPED_KEYS = ("app:", "prod:")


class RunMirror(QObject):
    _changed = Signal()

    def __init__(self, data_dir: Path, page_lookup=None, client=None, parent: QObject | None = None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.page_lookup = page_lookup or (lambda project, key: None)  # a live page showing those rows
        self.client = client
        self.store = None
        self._stop = threading.Event()
        self._queued = threading.Event()
        self._changed.connect(self.refresh)

    def start(self, store) -> None:
        """Catch up now, then follow the engine. Never starts an engine by itself."""
        self.store = store
        self.refresh()
        if self.client is not None:
            threading.Thread(target=self._follow, name="run-mirror", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _follow(self) -> None:
        for event in self.client.events(0, self._stop):
            # One look covers every event before it, so a replay of old ones doesn't queue a look each.
            if event.get("type") != "job.progress" and not self._queued.is_set():
                self._queued.set()
                self._changed.emit()  # queued to the GUI thread, which owns rows and pages

    # ---- manifests -> rows ------------------------------------------------
    def _project_for(self, run: dict[str, Any]):
        url = run.get("flowProjectUrl")
        if not url:
            return self.store.active  # shortcut: a job named only by project title lands here, until manifests carry its URL
        for project in self.store.list():
            if project.flow_url == url:
                return project
        project = self.store.create(self._free_name(str(run.get("name") or "Agent run")[:40]))
        project.set_flow(url, "")
        log.info("Agent run in a new Flow project: created project %r", project.name)
        return project

    def _free_name(self, name: str) -> str:
        taken = {p.name.lower() for p in self.store.list()}
        candidate, n = name, 2
        while candidate.lower() in taken:
            candidate, n = f"{name} {n}", n + 1
        return candidate

    def refresh(self) -> int:
        """Add missing agent rows and update existing ones. Returns how many rows it changed."""
        self._queued.clear()
        changed = 0
        for run in read_manifests(self.data_dir):
            jobs = [j for j in run.get("jobs") or [] if not str(j.get("idempotencyKey") or "").startswith(SKIPPED_KEYS)]
            if jobs:
                project = self._project_for(run)
                changed += sum(self._apply(project, job) for job in jobs)
        return changed

    def _apply(self, project, entry: dict[str, Any]) -> bool:
        spec = entry.get("spec") or {}
        key = "flow_video" if spec.get("kind") == "video" else "flow_image"
        state = row_state(entry)
        page = self.page_lookup(project, key)
        if page is not None:
            job = next((j for j in page.jobs if j.engine_job == entry["id"]), None)
            if job is None:
                job = Job(str(spec.get("prompt", "")), origin="agent", engine_job=entry["id"], **state)
                page.model.add_jobs([job])
                return True
            if self._same(job, state):
                return False
            for name, value in state.items():
                setattr(job, name, value)
            page.model.refresh_job(job.id)
            return True
        rows = project.rows(key)
        row = next((r for r in rows if r.get("engine_job") == entry["id"]), None)
        if row is None:
            job = Job(str(spec.get("prompt", "")), origin="agent", engine_job=entry["id"], **state)
            project.set_rows(key, [*rows, job_to_row(job)])
            return True
        job = row_to_job(row, 0)
        if self._same(job, state):
            return False
        for name, value in state.items():
            setattr(job, name, value)
        project.set_rows(key, [job_to_row(job) if r is row else r for r in rows])
        return True

    @staticmethod
    def _same(job: Job, state: dict[str, Any]) -> bool:
        return (job.status, job.outputs, job.error) == (state["status"], state["outputs"], state["error"])
