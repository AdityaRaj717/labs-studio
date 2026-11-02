"""Job rows shared by the queue, the table model and providers."""

from __future__ import annotations

import enum
import itertools
from dataclasses import dataclass, field
from pathlib import Path

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
    engine_key: str = ""  # idempotency key of the engine job this row is waiting on

    def reset(self) -> None:
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.preview = None
        self.progress_source = ""
        self.error = ""
