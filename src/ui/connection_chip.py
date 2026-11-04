"""Rail footer chip: which Google account and Flow project the engine is on, and the ways to look.

State comes from ``flow_status``, read off the GUI thread and only while no job holds the tab.
Menu: Open in Flow (bring the tab to the front), Show Flow now (a screenshot, opened in the
system viewer), Run Doctor (a pass or fail list shown here), Web Sessions.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QMessageBox

from src.i18n import tr
from src.ui.sidebar import SidebarButton

log = logging.getLogger(__name__)

READ_EVERY = 120.0


def chip_label(status: dict[str, Any] | None) -> tuple[str, bool]:
    """(label, connected) from a ``flow_status`` reply; None means the engine is not running."""
    if status is None:
        return tr("chip_engine_off"), False
    if not status.get("browser"):
        return tr("chip_no_chrome"), False
    if status.get("oauthRequired") or status.get("accountStatus") == "mismatch":
        return tr("chip_sign_in"), False
    account = status.get("account") or tr("chip_account_unknown")
    title = str(status.get("pageTitle") or "").removesuffix(" - Flow").strip()
    return (f"{account} · {title}" if status.get("flowAccessible") and title else account), True


def doctor_text(result: dict[str, Any]) -> str:
    """The doctor's verdict as lines: what it checked and each part of the page it did not find."""
    if result.get("ok"):
        return tr("chip_doctor_ok", n=result.get("checked", 0))
    lines = [tr("chip_doctor_failed", n=len(result.get("missing") or []), checked=result.get("checked", 0))]
    lines += [f"✗ {m.get('key')} ({m.get('where')})" for m in result.get("missing") or []]
    return "\n".join(lines)


class ConnectionChip(SidebarButton):
    _back = Signal(object)  # a callable to run on the GUI thread

    def __init__(self, call: Callable[[str, dict, float], dict], open_web_sessions: Callable[[], None], parent=None):
        super().__init__("plugs-connected", tr("chip_engine_off"), checkable=False, parent=parent)
        self.setObjectName("SidebarFooterButton")
        self.call, self.open_web_sessions = call, open_web_sessions
        self.connected = False
        self._busy = False
        self._read = False  # True once a flow_status reply is shown
        self._read_at = -READ_EVERY
        self._back.connect(lambda fn: fn())
        menu = QMenu(self)
        menu.addAction(tr("chip_open_flow"), lambda: self._run(lambda: self.call("flow_bring_to_front", {}, 20)))
        menu.addAction(tr("chip_show_flow"), self.show_flow)
        menu.addAction(tr("chip_doctor"), self.run_doctor)
        menu.addSeparator()
        menu.addAction(tr("chip_web_sessions"), self.open_web_sessions)
        self.clicked.connect(lambda: menu.exec(self.mapToGlobal(self.rect().topRight())))

    def show_status(self, status: dict[str, Any] | None) -> None:
        self.label, self.connected = chip_label(status)
        self._read = status is not None
        self.glyph = "plugs-connected" if self.connected else "warning"
        self.setToolTip(self.label)
        self.update()

    def refresh(self, idle: bool, running: bool) -> None:
        """Read the account again: only with an engine up (``running``) and the tab free (``idle``)."""
        if not running:
            self.show_status(None)
            self._read = False
            return
        if not self._read and not idle:
            self.label, self.connected, self.glyph = tr("chip_engine_busy"), True, "plugs-connected"
            self.setToolTip(self.label)
            self.update()
        # Every 2 min at most: a stale balance makes flow_status open Flow's account panel.
        if idle and not self._busy and time.monotonic() - self._read_at > READ_EVERY:
            self._busy, self._read_at = True, time.monotonic()
            self._run(lambda: self.call("flow_status", {}, 60), self._got, lambda exc: self._got(None))

    def _got(self, status) -> None:
        self._busy = False
        self.show_status(status)

    def _run(self, work, done=None, failed=None) -> None:
        def run() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - shown to the owner below
                log.info("Connection chip: %s", exc)
                self._back.emit(lambda: (failed or self._failed)(exc))
            else:
                if done is not None:
                    self._back.emit(lambda: done(result))
        threading.Thread(target=run, name="connection-chip", daemon=True).start()

    def _failed(self, exc: Exception) -> None:
        QMessageBox.warning(self, tr("chip_title"), str(exc) or type(exc).__name__)

    def show_flow(self) -> None:
        def opened(reply: dict) -> None:
            path = reply.get("screenshot")
            if path and Path(path).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self._run(lambda: self.call("flow_screenshot", {"name": "show-flow"}, 30), opened)

    def run_doctor(self) -> None:
        self._run(lambda: self.call("flow_doctor", {}, 120), self.show_doctor)

    def show_doctor(self, result: dict[str, Any]) -> None:
        box = QMessageBox.information if result.get("ok") else QMessageBox.warning
        box(self, tr("chip_doctor"), doctor_text(result))
