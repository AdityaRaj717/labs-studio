"""StatsHeader: one-line batch counters plus elapsed time."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from src.i18n import tr


class StatsHeader(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatsHeader")
        self.stats: dict[str, int] = {}
        self._started: float | None = None
        self._elapsed = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._render)
        self.update_stats({})

    def start_clock(self) -> None:
        if self._started is None:
            self._started = time.monotonic() - self._elapsed
            self._timer.start()

    def stop_clock(self) -> None:
        if self._started is not None:
            self._elapsed = time.monotonic() - self._started
            self._started = None
        self._timer.stop()
        self._render()

    def reset_clock(self) -> None:
        self._started = None
        self._elapsed = 0.0
        self._timer.stop()
        self._render()

    def update_stats(self, stats: dict[str, int]) -> None:
        self.stats = stats
        self._render()

    def _render(self) -> None:
        elapsed = time.monotonic() - self._started if self._started is not None else self._elapsed
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        keys = ("total", "queued", "running", "done", "failed", "stopped")
        counts = {k: self.stats.get(k, 0) for k in keys}
        self.setText(tr("gen_stats", elapsed=f"{h:d}:{m:02d}:{s:02d}", **counts))
