"""JobQueue: runs jobs through a provider on worker threads.

Qt-free. Callbacks fire on worker threads; ``ui.generator.queue_bridge``
turns them into Qt signals for the GUI.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from src.gen.models import RETRYABLE_STATUSES, Job, JobStatus, OutputFile
from src.gen.provider import Provider, ProviderError, RunContext, StopRequested

log = logging.getLogger(__name__)

Saver = Callable[[Job, list[OutputFile]], list[Path]]

# Called as hook(provider, job) on the worker thread each time a job ends
# (done, failed or stopped; not when it is re-queued for a retry). Phase 10's
# stats counter registers here.
FinishHook = Callable[[Provider, Job], None]
_finish_hooks: list[FinishHook] = []


def add_finish_hook(hook: FinishHook) -> None:
    if hook not in _finish_hooks:
        _finish_hooks.append(hook)


def remove_finish_hook(hook: FinishHook) -> None:
    if hook in _finish_hooks:
        _finish_hooks.remove(hook)


@dataclass
class QueueSettings:
    threads: int = 2
    delay_min: float = 0.0
    delay_max: float = 0.0
    max_retries: int = 1


def count_statuses(jobs: Iterable[Job]) -> dict[str, int]:
    counts = Counter(job.status.value for job in jobs)
    stats = {status.value: counts.get(status.value, 0) for status in JobStatus}
    stats["total"] = sum(counts.values())
    return stats


class JobQueue:
    def __init__(self, provider: Provider, saver: Saver,
                 on_update: Callable[[Job], None] | None = None,
                 on_finished: Callable[[], None] | None = None):
        self.provider = provider
        self.saver = saver
        self.on_update = on_update or (lambda job: None)
        self.on_finished = on_finished or (lambda: None)
        self.settings = QueueSettings()
        self.options: dict[str, Any] = {}

        self._lock = threading.RLock()
        self._pending: deque[Job] = deque()
        self._jobs: dict[int, Job] = {}
        self._active = 0
        self._stop = threading.Event()
        self._run_gate = threading.Event()  # set = running, clear = paused
        self._run_gate.set()
        self._idle = threading.Event()
        self._idle.set()

    # ---- control -----------------------------------------------------
    def start(self, jobs: Iterable[Job], options: dict[str, Any] | None = None,
              settings: QueueSettings | None = None) -> int:
        """Queue every pending/failed/stopped job in ``jobs`` and start workers."""
        if options is not None:
            self.options = dict(options)
        if settings is not None:
            self.settings = settings
        return self._enqueue(jobs)

    def retry(self, jobs: Iterable[Job]) -> int:
        """Re-queue failed/stopped jobs with the current options and settings."""
        return self._enqueue(jobs)

    def pause(self) -> None:
        self._run_gate.clear()
        log.info("Queue paused")

    def resume(self) -> None:
        self._run_gate.set()
        log.info("Queue resumed")

    @property
    def paused(self) -> bool:
        return not self._run_gate.is_set()

    def stop(self) -> None:
        """Drop queued jobs (marked stopped) and ask running jobs to stop."""
        self._stop.set()
        self._run_gate.set()
        with self._lock:
            dropped = list(self._pending)
            self._pending.clear()
            for job in dropped:
                job.status = JobStatus.STOPPED
        for job in dropped:
            self.on_update(job)
        log.info("Queue stopped (%d queued jobs dropped)", len(dropped))

    def is_running(self) -> bool:
        with self._lock:
            return self._active > 0

    def wait(self, timeout: float | None = None) -> bool:
        """Block until all workers have exited. Returns False on timeout."""
        return self._idle.wait(timeout)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return count_statuses(self._jobs.values())

    def forget(self, jobs: Iterable[Job]) -> None:
        with self._lock:
            for job in jobs:
                self._jobs.pop(job.id, None)

    # ---- internals ---------------------------------------------------
    def _enqueue(self, jobs: Iterable[Job]) -> int:
        queued = []
        with self._lock:
            self._stop.clear()
            for job in jobs:
                if job.status in RETRYABLE_STATUSES and job not in self._pending:
                    job.reset()
                    job.status = JobStatus.QUEUED
                    job.attempts = 0
                    self._pending.append(job)
                    self._jobs[job.id] = job
                    queued.append(job)
            want = min(max(1, int(self.settings.threads)), len(self._pending))
            for _ in range(max(0, want - self._active)):
                self._active += 1
                self._idle.clear()
                threading.Thread(target=self._worker, name="gen-worker", daemon=True).start()
        for job in queued:
            self.on_update(job)
        if queued:
            log.info("Queued %d job(s) on %s", len(queued), self.provider.name)
        return len(queued)

    def _next_job(self) -> tuple[Job | None, bool]:
        """Pop the next job, or retire this worker (under the lock) when none is left.

        Returns ``(job, False)``, or ``(None, last)`` where ``last`` is True for
        the worker that leaves the queue idle.
        """
        with self._lock:
            if self._pending and not self._stop.is_set():
                return self._pending.popleft(), False
            self._active -= 1
            if self._active == 0:
                self._idle.set()
                return None, True
            return None, False

    def _worker(self) -> None:
        first = True
        while True:
            while not self._run_gate.wait(0.1):
                pass
            if not first and not self._stop.is_set() and self._pending:
                lo, hi = sorted((float(self.settings.delay_min), float(self.settings.delay_max)))
                if hi > 0:
                    self._stop.wait(random.uniform(lo, hi))
                if not self._run_gate.is_set():
                    continue  # paused during the delay: wait at the gate again
            job, last = self._next_job()
            if job is None:
                break
            first = False
            self._run(job)
        if last:
            log.info("Queue finished: %s", self.stats())
            self.on_finished()

    def _run(self, job: Job) -> None:
        with self._lock:
            job.status = JobStatus.RUNNING
            job.attempts += 1
            job.progress = 0.0
            job.error = ""
            job.progress_source, job.stage, job.tiles = "", "", 1
            job.started_at = time.time()  # an engine job replaces it with Flow's submit time
        self.on_update(job)

        def progress(p: float) -> None:
            job.progress = max(0.0, min(1.0, float(p)))
            self.on_update(job)

        def partial(path: Path) -> None:
            job.preview = path
            self.on_update(job)

        def note(source: str) -> None:
            job.progress_source = source

        def info(**fields) -> None:
            for name, value in fields.items():
                setattr(job, name, value)
            self.on_update(job)

        ctx = RunContext(progress=progress, should_stop=self._stop.is_set, partial=partial, note=note, info=info)
        try:
            files = self.provider.generate(job, self.options, ctx)
            paths = self.saver(job, files)
            with self._lock:
                job.outputs = paths
                job.preview = None
                job.progress = 1.0
                job.status = JobStatus.DONE
        except StopRequested:
            job.status = JobStatus.STOPPED
        except ProviderError as exc:
            with self._lock:
                job.error = str(exc)
                if exc.retryable and job.attempts <= self.settings.max_retries and not self._stop.is_set():
                    job.status = JobStatus.QUEUED
                    self._pending.append(job)
                    log.warning("Job %d retrying after: %s", job.index, exc)
                else:
                    job.status = JobStatus.FAILED
                    log.error("Job %d failed: %s", job.index, exc)
            if exc.stop_queue:
                log.error("Stopping the queue: %s", exc)
                self.stop()
        except Exception as exc:  # noqa: BLE001 - one bad job must not kill the worker
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            log.exception("Job %d crashed", job.index)
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.STOPPED):
            for hook in list(_finish_hooks):
                try:
                    hook(self.provider, job)
                except Exception:  # noqa: BLE001 - a broken hook must not kill the worker
                    log.exception("Finish hook failed")
        self.on_update(job)
