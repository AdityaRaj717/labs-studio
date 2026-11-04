"""Job rows shared by the queue, the table model and providers."""

from __future__ import annotations

import enum
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ids = itertools.count(1)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


# Statuses a job can be (re)queued from.
RETRYABLE_STATUSES = (JobStatus.PENDING, JobStatus.FAILED, JobStatus.STOPPED)


@dataclass
class OutputFile:
    """One generated file, still in memory; ``output.save_outputs`` writes it."""

    data: bytes
    ext: str = "png"


@dataclass
class Take:
    """One attempt at a Production Item, as the engine keeps it (``item.takes[]``)."""
    n: int
    prompt: str = ""
    refs_used: list[str] = field(default_factory=list)
    status: str = ""  # generating, done, failed
    file: str = ""
    quoted_credits: int = 0
    verdict: str = ""  # "", approved, rejected
    actor: str = ""
    at: str = ""
    note: str = ""

    @classmethod
    def from_engine(cls, take: dict) -> "Take":
        return cls(n=int(take.get("n") or 0), prompt=str(take.get("prompt") or ""),
                   refs_used=[str(r) for r in take.get("refs_used") or []], status=str(take.get("status") or ""),
                   file=str(take.get("file") or ""), quoted_credits=int(take.get("quoted_credits") or 0),
                   verdict=str(take.get("verdict") or ""), actor=str(take.get("actor") or ""),
                   at=str(take.get("at") or ""), note=str(take.get("note") or ""))


@dataclass
class Job:
    prompt: str
    index: int = 0
    refs: list[Path] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    outputs: list[Path] = field(default_factory=list)
    error: str = ""
    attempts: int = 0
    id: int = field(default_factory=lambda: next(_ids))
    character: str = ""  # attached character id (Phase 6), "" = none
    character_refs: list[Path] = field(default_factory=list)  # the refs in ``refs`` it brought
    cast: list[str] = field(default_factory=list)  # more character ids in the shot (Phase 14b)
    scenes: list[str] = field(default_factory=list)  # scene (place) ids (Phase 14b)
    scene_refs: list[Path] = field(default_factory=list)  # the refs in ``refs`` the scenes brought
    preview: Path | None = None  # shown until ``outputs`` exist
    progress_source: str = ""  # "flow": Flow's own percent; "phase": only the engine's stage
    stage: str = ""  # the engine job's state while live (see ``src.gen.progress``)
    started_at: float | None = None  # epoch s: Flow submit for engine jobs, attempt start otherwise
    tiles: int = 1  # running tiles behind Flow's percent
    engine_key: str = ""  # idempotency key of the engine job this row is waiting on
    origin: str = ""  # "agent": an outside agent's job; the engine runs it, never this row's Start
    engine_job: str = ""  # the engine's job id behind an agent row
    production_id: str = ""  # set on a Production's rows; the engine's review truth is what they show
    item_id: str = ""
    review: str = ""  # "", pending_review, approved, rejected or regenerating
    take: int = 0  # the Take a verdict on this row names
    latest_take: int = 0  # the newest Take, which a regeneration names
    stale: str = ""  # the dependency IDs whose Approved Take changed since this row's
    ref_labels: list[str] = field(default_factory=list)  # Cast names
    takes: list[Take] = field(default_factory=list)  # a Production Item's every Take, oldest first
    start_frame: Path | None = None  # video: Flow's Frames mode, the first frame
    end_frame: Path | None = None  # video: Frames mode, the last frame
    overrides: dict[str, Any] = field(default_factory=dict)  # this shot's own settings (``SHOT_KEYS``)
    production_stage: str = ""  # reference, still or animation: the Production stage this Item belongs to

    def reset(self) -> None:
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.preview = None
        self.progress_source = ""
        self.stage = ""
        self.started_at = None
        self.tiles = 1
        self.error = ""
