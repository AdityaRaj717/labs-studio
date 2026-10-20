"""QueueBridge: JobQueue callbacks (worker threads) -> Qt signals (GUI thread)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.gen.models import Job


class QueueBridge(QObject):
    job_updated = Signal(int)  # job id
    finished = Signal()

    # Emitting from a worker thread is safe: receivers in the GUI thread get
    # the signal through a queued connection.
    def on_update(self, job: Job) -> None:
        self.job_updated.emit(job.id)

    def on_finished(self) -> None:
        self.finished.emit()
