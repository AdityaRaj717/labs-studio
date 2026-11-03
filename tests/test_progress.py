"""A row says only what the engine and Flow know: Flow's percent, or the stage and the time since submit."""

from __future__ import annotations

from src.gen.models import Job, JobStatus
from src.gen.progress import parse_ts, progress_view
from src.gen.provider import RunContext
from src.gen.web_flow_image import report_event
from src.web.engine_client import row_state


def _ctx(job: Job) -> RunContext:
    def progress(p):
        job.progress = p

    def note(source):
        job.progress_source = source

    def info(**fields):
        for name, value in fields.items():
            setattr(job, name, value)

    return RunContext(progress=progress, should_stop=lambda: False, note=note, info=info)


def test_percent_only_from_flow():
    job = Job("p", status=JobStatus.RUNNING, progress=0.4, progress_source="phase", stage="preparing")
    assert progress_view(job, 0).percent is None
    job.progress_source, job.stage = "flow", "generating"
    assert progress_view(job, 0).percent == 40


def test_transition_clears_stale_percent():
    job = Job("p", status=JobStatus.RUNNING)
    ctx = _ctx(job)
    report_event({"type": "job.progress", "progress": 77, "source": "flow", "tiles": 4}, ctx)
    assert job.tiles == 4 and progress_view(job, 0).percent == 77
    report_event({"type": "job.transition", "state": "downloading", "submittedAt": "2026-11-03T10:00:00.000Z"}, ctx)
    view = progress_view(job, parse_ts("2026-11-03T10:00:42.000Z"))
    assert view.percent is None and view.stage == "downloading" and view.elapsed_s == 42


def test_queued_agent_job_is_not_live():
    state = row_state({"state": "queued", "data": {}})
    assert state["status"] is JobStatus.QUEUED and state["started_at"] is None


def test_clock_survives_app_restart():
    # The submit time comes from the manifest, so a fresh app shows the same elapsed time.
    state = row_state({"state": "generating", "submittedAt": "2026-11-03T10:00:00.000Z", "data": {}})
    job = Job("p", **state)
    assert progress_view(job, parse_ts("2026-11-03T10:01:05Z")).elapsed_s == 65
    assert progress_view(job, 0).percent is None  # no Flow percent read yet
