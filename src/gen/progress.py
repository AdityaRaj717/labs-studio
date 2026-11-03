"""What a row may honestly say about a running job: Flow's own percent, or the stage and how long."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.gen.models import Job, JobStatus

LIVE_STAGES = ("queued", "preparing", "submitted", "generating", "downloading", "verifying")


@dataclass(frozen=True)
class ProgressView:
    stage: str  # queued, preparing, submitted, generating, downloading, verifying, or ""
    percent: int | None  # only while source == "flow" and stage == "generating"
    elapsed_s: int | None  # from the engine's submitted_at; local clock only for non-engine providers
    tiles: int  # running tiles Flow has; 1 unless the engine says more


def parse_ts(value) -> float | None:
    """An engine timestamp (ISO text or epoch ms) as epoch seconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def progress_view(job: Job, now: float) -> ProgressView:
    live = job.status in (JobStatus.RUNNING, JobStatus.QUEUED)
    if not live:
        return ProgressView("", None, None, 1)
    stage = job.stage
    flow = job.progress_source == "flow" and stage in ("generating", "")
    percent = round(job.progress * 100) if flow and job.status is JobStatus.RUNNING else None
    elapsed = max(0, int(now - job.started_at)) if job.started_at is not None else None
    return ProgressView(stage, percent, elapsed, max(1, job.tiles))


def clock(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def stage_word(view: ProgressView) -> str:
    from src.i18n import tr
    return tr(f"stage_{view.stage}") if view.stage in LIVE_STAGES else ""
