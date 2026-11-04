"""Credit meter in the run bar: Flow's balance with its age, and the engine's own tallies.

``flow_status`` is asked on a worker thread and only while idle, since a job holds the tab.
The month spend and image quota are what the engine counted; hand use in Flow is not in them.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel

from src.i18n import tr

log = logging.getLogger(__name__)
RETRY_MS = 5000


def age_text(at: str | None, now: datetime | None = None) -> str:
    """'just now', '4 min ago', '3 h ago', '2 d ago' for an ISO time; '' when unknown."""
    if not at:
        return ""
    try:
        seen = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    minutes = int(((now or datetime.now(timezone.utc)) - seen).total_seconds() // 60)
    if minutes < 1:
        return tr("meter_age_now")
    if minutes < 60:
        return tr("meter_age_min", n=minutes)
    if minutes < 48 * 60:
        return tr("meter_age_h", n=minutes // 60)
    return tr("meter_age_d", n=minutes // 1440)


def meter_text(status: dict[str, Any], now: datetime | None = None) -> str:
    parts = []
    balance = status.get("balance")
    if balance is None:
        parts.append(tr("meter_balance_unknown"))
    else:
        age = age_text(status.get("balanceAt"), now)
        parts.append(tr("meter_balance", n=f"{balance:,}") + (f" ({age})" if age else ""))
    ledger = status.get("ledger") or {}
    if ledger.get("monthTotal") is not None:
        parts.append(tr("meter_month", n=f"{ledger['monthTotal']:,}"))
    for quota in (ledger.get("todayQuota") or {}).values():
        if quota.get("limit") is not None:
            parts.append(tr("meter_quota", model=quota["model"], left=quota["remaining"], limit=quota["limit"]))
    return "  ·  ".join(parts)


def stale(status: dict[str, Any], now: datetime | None = None, minutes: int = 30) -> bool:
    """A balance older than ``minutes`` (or never read) is labelled as such, not shown as current."""
    at = status.get("balanceAt")
    if status.get("balance") is None or not at:
        return True
    try:
        seen = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return ((now or datetime.now(timezone.utc)) - seen).total_seconds() > minutes * 60


class CreditMeter(QLabel):
    """Click to read again. ``fetch`` is ``flow_mcp().status``; ``idle`` says the tab is free."""
    _got = Signal(object)

    def __init__(self, fetch: Callable[[], dict[str, Any]], idle: Callable[[], bool], parent=None):
        super().__init__(parent)
        self.setObjectName("CreditMeter")
        self.fetch, self.idle = fetch, idle
        self._busy = False
        self.status: dict[str, Any] | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("meter_tip"))
        self._got.connect(self.show_status)
        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS)  # the tab was busy: ask again later
        self._retry.timeout.connect(self.refresh)
        self._clock = QTimer(self, interval=60_000)  # "just now" turns into "4 min ago" without a new read
        self._clock.timeout.connect(self._redraw)
        self._clock.start()

    def refresh(self) -> None:
        if self._busy or not self.isVisibleTo(self.parentWidget()):
            return
        if not self.idle():  # a run just ended and the engine may still hold the tab
            self._retry.start()
            return
        self._busy = True
        threading.Thread(target=self._read, name="credit-meter", daemon=True).start()

    def _read(self) -> None:
        try:
            status = self.fetch()
        except Exception as exc:  # noqa: BLE001 - the meter just says it could not read
            log.info("Credit meter: %s", exc)
            status = None
        self._got.emit(status)

    def show_status(self, status: dict[str, Any] | None) -> None:
        self._busy = False
        self.status = status
        if status is None:
            self.setText(tr("meter_unreachable"))
            self.setProperty("stale", True)
        else:
            self._redraw()
            return
        self.style().unpolish(self)
        self.style().polish(self)

    def _redraw(self) -> None:
        if self.status is None:
            return
        self.setText(meter_text(self.status))
        self.setProperty("stale", stale(self.status))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        self.refresh()
        super().mousePressEvent(event)
