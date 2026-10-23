"""Pacing for web-session sites: a random gap between jobs and a daily cap.

The count for each site lives in settings at ``web.usage.<site>`` as
``{"date": "YYYY-MM-DD", "count": n}`` and resets when the date changes.
One "use" is one prompt submitted to the site, whatever the image count.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import date
from typing import Callable

log = logging.getLogger(__name__)


class Pacer:
    def __init__(self, site: str, store=None, today: Callable[[], date] = date.today,
                 clock: Callable[[], float] = time.monotonic):
        if store is None:
            from src import config

            store = config.settings()
        self.site = site
        self.store = store
        self.today = today
        self.clock = clock
        self._last_end: float | None = None
        self._lock = threading.Lock()

    # ---- daily cap ---------------------------------------------------
    @property
    def cap(self) -> int:
        return int(self.store.get(f"web.caps.{self.site}", 0) or 0)

    def used_today(self) -> int:
        rec = self.store.get(f"web.usage.{self.site}") or {}
        if rec.get("date") != self.today().isoformat():
            return 0
        return int(rec.get("count", 0))

    def cap_reached(self) -> bool:
        return self.cap > 0 and self.used_today() >= self.cap

    def record_use(self) -> int:
        with self._lock:
            n = self.used_today() + 1
            self.store.set(f"web.usage.{self.site}", {"date": self.today().isoformat(), "count": n})
            return n

    # ---- gap between jobs ---------------------------------------------
    def gap(self) -> float:
        lo = float(self.store.get("web.gap_min", 0) or 0)
        hi = float(self.store.get("web.gap_max", 0) or 0)
        lo, hi = sorted((max(0.0, lo), max(0.0, hi)))
        return random.uniform(lo, hi) if hi > 0 else 0.0

    def wait_turn(self, should_stop: Callable[[], bool]) -> bool:
        """Sleep out the rest of a random gap since the last job ended.

        Returns False if ``should_stop`` turned true while waiting.
        """
        if self._last_end is None:
            return not should_stop()
        until = self._last_end + self.gap()
        if until > self.clock():
            log.info("%s: waiting %.0fs before the next job", self.site, until - self.clock())
        while self.clock() < until:
            if should_stop():
                return False
            time.sleep(min(0.25, max(0.0, until - self.clock())))
        return not should_stop()

    def mark_done(self) -> None:
        self._last_end = self.clock()
