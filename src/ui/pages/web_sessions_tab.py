"""Settings → Web Sessions: the Chrome used by web-session providers, one row per site."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src import config
from src.i18n import tr
from src.web.engine_client import uses_today

log = logging.getLogger(__name__)

SITE_TITLES = {"flow": "Google Flow"}


class _Bridge(QObject):
    """Carries results from helper threads back to the GUI thread."""

    done = Signal(str, str, object)  # site, action, result (str or Exception)


class PathEdit(QWidget):
    def __init__(self, key: str, store, folder: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.key, self.store, self.folder = key, store, folder
        self.edit = QLineEdit(str(store.get(key, "") or ""))
        self.edit.editingFinished.connect(lambda: store.set(key, self.edit.text().strip()))
        browse = QPushButton(tr("gen_browse"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(browse)

    def _browse(self) -> None:
        if self.folder:
            path = QFileDialog.getExistingDirectory(self, tr("gen_browse"), self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("gen_browse"), self.edit.text(), "chrome.exe (*.exe)")
        if path:
            self.edit.setText(path)
            self.store.set(self.key, path)


class SiteRow(QGroupBox):
    def __init__(self, site: str, store, run_async, parent: QWidget | None = None):
        super().__init__(SITE_TITLES.get(site, site), parent)
        self.site = site
        self.store = store
        self.run_async = run_async

        self.status = QLabel(tr("web_status_unknown"))
        self.status.setWordWrap(True)
        self.usage = QLabel()
        self.cap = QSpinBox()
        self.cap.setRange(0, 1000)
        self.cap.setSpecialValueText(tr("web_cap_none"))
        self.cap.setValue(int(store.get(f"web.caps.{site}", 0) or 0))
        self.cap.valueChanged.connect(self._set_cap)

        self.btn_launch = QPushButton(tr("web_launch"))
        self.btn_check = QPushButton(tr("web_check"))
        self.btn_diag = QPushButton(tr("web_diagnose"))
        self.btn_launch.clicked.connect(lambda: self.run_async(self.site, "launch"))
        self.btn_check.clicked.connect(lambda: self.run_async(self.site, "check"))
        self.btn_diag.clicked.connect(lambda: self.run_async(self.site, "diagnose"))

        buttons = QHBoxLayout()
        for b in (self.btn_launch, self.btn_check, self.btn_diag):
            buttons.addWidget(b)
        buttons.addStretch(1)
        form = QFormLayout()
        form.addRow(tr("web_logged_in"), self.status)
        form.addRow(tr("web_used_today"), self.usage)
        form.addRow(tr("web_daily_cap"), self.cap)
        form.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 6)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.refresh_usage()

    def _set_cap(self, value: int) -> None:
        self.store.set(f"web.caps.{self.site}", int(value))
        self.refresh_usage()

    def refresh_usage(self) -> None:
        cap = int(self.store.get(f"web.caps.{self.site}", 0) or 0)
        data_dir = Path(self.store.get("web.diag_dir", r"D:\glabs_web\diag")).parent / "flow-mcp"
        self.usage.setText(tr("web_usage", used=uses_today(data_dir),
                              cap=cap if cap else tr("web_cap_none")))

    def set_busy(self, busy: bool) -> None:
        for b in (self.btn_launch, self.btn_check, self.btn_diag):
            b.setEnabled(not busy)


class WebSessionsTab(QWidget):
    def __init__(self, store=None, session=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store if store is not None else config.settings()
        self._session = session
        self.bridge = _Bridge(self)
        self.bridge.done.connect(self._on_done)

        note = QLabel(tr("web_note"))
        note.setWordWrap(True)
        note.setObjectName("PageBody")

        browser = QGroupBox(tr("web_browser"))
        form = QFormLayout(browser)
        form.setContentsMargins(0, 2, 0, 6)
        form.addRow(tr("web_chrome_path"), PathEdit("web.chrome_path", self.store, folder=False))
        form.addRow(tr("web_profile_dir"), PathEdit("web.profile_dir", self.store, folder=True))
        form.addRow(tr("web_diag_dir"), PathEdit("web.diag_dir", self.store, folder=True))
        form.addRow(tr("web_mcp_dir"), PathEdit("web.flow_mcp_dir", self.store, folder=True))
        node = QLineEdit(str(self.store.get("web.node_path", "node") or "node"))
        node.editingFinished.connect(lambda: self.store.set("web.node_path", node.text().strip() or "node"))
        form.addRow(tr("web_node_path"), node)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(self.store.get("web.port", 9333)))
        self.port.valueChanged.connect(lambda v: self.store.set("web.port", int(v)))
        form.addRow(tr("web_port"), self.port)
        for key, label in (("web.gap_min", "web_gap_min"), ("web.gap_max", "web_gap_max")):
            spin = QDoubleSpinBox()
            spin.setRange(0, 3600)
            spin.setDecimals(0)
            spin.setValue(float(self.store.get(key, 0) or 0))
            spin.valueChanged.connect(lambda v, key=key: self.store.set(key, float(v)))
            form.addRow(tr(label), spin)

        self.rows = {site: SiteRow(site, self.store, self.run_async) for site in SITE_TITLES}
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 8, 10, 8)
        layout.addWidget(note)
        layout.addWidget(browser)
        for row in self.rows.values():
            layout.addWidget(row)
        layout.addStretch(1)
        scroll = QScrollArea()  # the form is taller than the minimum window
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @property
    def session(self):
        if self._session is None:
            from src.web.session import session

            self._session = session()
        return self._session

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        for row in self.rows.values():
            row.refresh_usage()

    # ---- actions (run off the GUI thread; the browser calls can take a while)
    def run_async(self, site: str, action: str) -> None:
        self.rows[site].set_busy(True)
        self.rows[site].status.setText(tr("web_working"))
        threading.Thread(target=self._work, args=(site, action), daemon=True).start()

    def _work(self, site: str, action: str) -> None:
        try:
            result = self.do_action(site, action)
        except Exception as exc:  # noqa: BLE001 - shown in the row
            log.warning("Web Sessions %s/%s failed: %s", site, action, exc)
            result = exc
        self.bridge.done.emit(site, action, result)

    def do_action(self, site: str, action: str):
        if action == "launch":
            return self.session.open_site(site)
        if action == "check":
            return self.session.login_state(site)
        if action == "diagnose":
            from src.web.diagnose import diagnose

            return diagnose(site, self.session.backend)
        raise ValueError(action)

    def _on_done(self, site: str, action: str, result) -> None:
        row = self.rows[site]
        row.set_busy(False)
        row.refresh_usage()
        if isinstance(result, Exception):
            row.status.setText(tr("web_error", error=str(result).splitlines()[0] if str(result) else type(result).__name__))
        elif action == "diagnose":
            row.status.setText(tr("web_diag_saved", path=str(result)))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result)))
        else:
            row.status.setText(tr(f"web_state_{result}"))
