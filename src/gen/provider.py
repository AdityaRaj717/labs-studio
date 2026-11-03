"""Provider interface every generator backend implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.gen.models import Job, OutputFile


class ProviderError(Exception):
    """A job failed. ``stop_queue`` also stops the rest of the batch (web
    providers raise it for sign-in walls, CAPTCHAs and spent quota)."""

    def __init__(self, message: str, retryable: bool = False, stop_queue: bool = False):
        super().__init__(message)
        self.retryable = retryable and not stop_queue
        self.stop_queue = stop_queue


class StopRequested(Exception):
    """Raised by a provider when ``ctx.should_stop()`` turned true mid-job."""


@dataclass
class ConfigField:
    """One setting on a page's config panel.

    kind: ``choice`` | ``int`` | ``float`` | ``bool`` | ``folder`` | ``text``.
    Choice labels are ``tr(option_prefix + value)`` when a prefix is given,
    else the raw value.
    """

    key: str
    label_key: str
    kind: str
    default: Any = None
    options: list[str] = field(default_factory=list)
    minimum: float = 0
    maximum: float = 9999
    option_prefix: str = ""
    depends_on: str = ""  # another field's key: ``options_by[its value]`` replaces ``options``
    options_by: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Estimate:
    """What a Start would ask for, before anything is spent. ``credits`` None: the provider bills it.
    ``note`` is a language key that replaces the credit line."""

    shots: int
    credits: int | None
    note: str = ""


@dataclass
class RunContext:
    """Handed to ``Provider.generate``: report progress, check for stop."""

    progress: Callable[[float], None]
    should_stop: Callable[[], bool]
    partial: Callable[[Path], None] = lambda path: None  # a first look at the result (sets ``Job.preview``)
    note: Callable[[str], None] = lambda source: None  # whose number ``progress`` is: "flow" or "phase"
    info: Callable[..., None] = lambda **fields: None  # engine truth: stage, started_at, tiles


class Provider:
    key = "base"
    name = "Base provider"
    max_count = 8  # takes per shot the provider accepts

    def estimate(self, jobs: list[Job], options: dict[str, Any]) -> Estimate:
        return Estimate(len(jobs), None, "gen_estimate_billed")

    def config_fields(self) -> list[ConfigField]:
        return []

    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        raise NotImplementedError
