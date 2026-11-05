"""Show what agents run on the shared engine as rows in the app.

The manifests are the truth, so a run made while the app was closed shows on the next start.
Engine events only say when to look again. Jobs the app started (key ``app:``) already have
their row. A Production's jobs (key ``prod:``) don't get one: its Items do, one row each, from
``flow_production_status`` at the start and ``production.item`` events after.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from src.gen.models import Job, JobStatus, Take
from src.gen.progress import parse_ts
from src.i18n import tr
from src.projects.store import job_to_row, row_to_job
from src.web.engine_client import EngineError, EngineToolError, read_manifests, row_state

log = logging.getLogger(__name__)

SKIPPED_KEYS = ("app:", "prod:")
ITEM_STATUS = {
    "planned": JobStatus.QUEUED,  # not PENDING, so Start can never submit it
    "generating": JobStatus.RUNNING,
    "pending_review": JobStatus.DONE,
    "approved": JobStatus.DONE,
    "rejected": JobStatus.DONE,
    "regenerating": JobStatus.RUNNING,
    "failed": JobStatus.FAILED,
}
REVIEW_STATES = ("pending_review", "approved", "rejected", "regenerating")


def banner_text(summary: dict[str, Any], name: str) -> str:
    """One line: ``Name: references 4/4 · stills 6/8 · 14 of 60 credits · waiting for your review``."""
    parts = []
    for stage, key in (("reference", "production_references"), ("still", "production_stills"),
                       ("animation", "production_animations")):
        counts = (summary.get("stages") or {}).get(stage) or {}
        if counts.get("total"):
            parts.append(f"{tr(key)} {counts.get('approved', 0)}/{counts['total']}")
    credits = summary.get("credits") or {}
    if credits.get("max") is not None:
        parts.append(tr("production_credits", spent=credits.get("spent", 0), max=credits["max"]))
    status = summary.get("status")
    if status == "paused":
        reason = str((summary.get("paused") or {}).get("reason") or "").replace("_", " ")
        parts.append(tr("production_paused", reason=reason))
    elif status:
        parts.append(tr(f"production_{status}"))
    return f"{name}: {' · '.join(parts)}"


def item_fields(event: dict[str, Any]) -> dict[str, Any]:
    """A ``production.item`` as row fields, per the spec's mapping."""
    state = event.get("state")
    status = ITEM_STATUS.get(state, JobStatus.QUEUED)
    latest = int(event.get("take") or 0)
    approved = event.get("approved_take")
    return {
        "prompt": str(event.get("prompt") or ""),
        "production_id": str(event["production_id"]),
        "item_id": str(event["item"]),
        "status": status,
        "review": state if state in REVIEW_STATES else "",
        "take": int(approved) if state == "approved" and approved is not None else latest,
        "latest_take": latest,
        "stale": ", ".join(event.get("stale") or []),
        "production_stage": str(event.get("stage") or ""),
        "ref_labels": [str(n) for n in event.get("ref_names") or []],
        "outputs": [Path(event["file"])] if event.get("file") else [],
        "error": str(event.get("error") or "") if not isinstance(event.get("error"), dict)
        else str(event["error"].get("message") or ""),
        "progress": 1.0 if status is JobStatus.DONE else float(event.get("progress") or 0) / 100,
        "progress_source": str(event.get("source") or ""),
        "stage": str(event.get("job_state") or "") if status in (JobStatus.RUNNING, JobStatus.QUEUED) else "",
        "started_at": parse_ts(event.get("submitted_at")),
        "tiles": int(event.get("tiles") or 1),
        # Only a full status read carries the history; an event without it keeps what the row has.
        **({"takes": [Take.from_engine(t) for t in event["takes"]]} if "takes" in event else {}),
    }


def apply_item(job: Job, event: dict[str, Any]) -> None:
    for name, value in item_fields(event).items():
        setattr(job, name, value)


class HealthWatch(QObject):
    """Asks the engine's ``/health`` every few seconds off the GUI thread; emits an EngineHealth or None."""
    changed = Signal(object)

    def __init__(self, client, interval: float = 5.0, parent: QObject | None = None):
        super().__init__(parent)
        self.client, self.interval = client, interval
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="engine-health", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.changed.emit(self.client.health())
            self._stop.wait(self.interval)


class RunMirror(QObject):
    _changed = Signal()
    _production = Signal(object)
    _progress = Signal(object)

    def __init__(self, data_dir: Path, page_lookup=None, client=None, parent: QObject | None = None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.page_lookup = page_lookup or (lambda project, key: None)  # a live page showing those rows
        self.client = client
        self.store = None
        self._stop = threading.Event()
        self._queued = threading.Event()
        self._changed.connect(self.refresh)
        self._production.connect(self.apply_production_event)
        self._progress.connect(self.apply_progress)

    def start(self, store) -> None:
        """Catch up now, then follow the engine. Never starts an engine by itself."""
        self.store = store
        self.refresh()
        if self.client is not None:
            threading.Thread(target=self._follow, name="run-mirror", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _follow(self) -> None:
        caught_up = self.catch_up()
        for event in self.client.events(0, self._stop):
            if not caught_up or event.get("type") == "reset":  # the engine wasn't up before, or came back
                caught_up = self.catch_up()
            if str(event.get("type")).startswith("production."):
                self._production.emit(event)
            elif event.get("type") == "job.progress":
                self._progress.emit(event)  # Flow's own percent for an agent row
            # One look covers every event before it, so a replay of old ones doesn't queue a look each.
            elif event.get("type") != "job.progress" and not self._queued.is_set():
                self._queued.set()
                self._changed.emit()  # queued to the GUI thread, which owns rows and pages

    def catch_up(self) -> bool:
        """Off the GUI thread: every Production's Items, read once. False while the engine is down."""
        for run in read_manifests(self.data_dir):
            try:
                production = json.loads((Path(run["dir"]) / "production.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                continue  # not a Production's run
            try:
                self._read_production(production["id"], run["id"])
            except (EngineError, TimeoutError) as exc:
                log.debug("Production rows wait for the engine: %s", exc)
                return False
            except EngineToolError as exc:  # one Production's trouble must not hide the others
                log.warning("Production %s not read: %s", production.get("id"), exc)
        return True

    def _read_production(self, production_id: str, run_id: str) -> None:
        cursor = 0
        while cursor is not None:
            reply = self.client.call("flow_production_status", {"production_id": production_id, "detail": "full",
                                                                "cursor": cursor})
            for item in reply.get("items") or []:
                self._production.emit({**item, "type": "production.item", "runId": run_id})
            cursor = reply.get("next_cursor")
        self._production.emit({**reply, "type": "production.summary", "runId": run_id})

    # ---- Production events -> rows and banner ------------------------------
    def _run(self, run_id: str) -> dict[str, Any]:
        return next((r for r in read_manifests(self.data_dir) if r.get("id") == run_id), {})

    def apply_production_event(self, event: dict[str, Any]) -> None:
        run = self._run(event.get("runId"))
        project = self._project_for(run)
        if event.get("type") == "production.item":
            self._apply_item(project, "flow_video" if event.get("stage") == "animation" else "flow_image", event)
        elif event.get("type") == "production.summary":
            name = str(event.get("name") or run.get("name") or "")
            project.set("production_banner", banner_text(event, name))
            for key in ("flow_image", "flow_video"):
                page = self.page_lookup(project, key)
                if page is not None:
                    page.set_production_summary(event, name)

    def _apply_item(self, project, key: str, event: dict[str, Any]) -> None:
        same_item = (str(event["production_id"]), str(event["item"]))
        page = self.page_lookup(project, key)
        if page is not None:
            job = next((j for j in page.jobs if (j.production_id, j.item_id) == same_item), None)
            if job is None:
                page.model.add_jobs([Job(origin="agent", **item_fields(event))])
            else:
                apply_item(job, event)
                page.model.refresh_job(job.id)
            return
        rows = project.rows(key)
        row = next((r for r in rows if (r.get("production_id"), r.get("item_id")) == same_item), None)
        if row is None:
            project.set_rows(key, [*rows, job_to_row(Job(origin="agent", **item_fields(event)))])
            return
        job = row_to_job(row, 0)
        apply_item(job, event)
        project.set_rows(key, [job_to_row(job) if r is row else r for r in rows])

    def apply_progress(self, event: dict[str, Any]) -> None:
        """A live percent goes to an open page's agent row only; saved rows keep no percent."""
        if event.get("progress") is None:
            return
        project = self._project_for(self._run(event.get("runId")))
        for key in ("flow_image", "flow_video"):
            page = self.page_lookup(project, key)
            job = next((j for j in page.jobs if j.engine_job == event.get("jobId")), None) if page else None
            if job is not None:
                job.progress = float(event["progress"]) / 100
                job.progress_source = str(event.get("source") or "")
                job.tiles = int(event.get("tiles") or 1)
                page.model.refresh_job(job.id)

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
        return ((job.status, job.outputs, job.error, job.stage, job.started_at)
                == (state["status"], state["outputs"], state["error"], state["stage"], state["started_at"]))
