"""Webhook API page: local job-submit server controls, plus the Stats tab."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from src import features
from src.i18n import tr
from src.ui.kit import header_row, intro_label, page_layout
from src.stats.store import FIELDS, StatsStore, default_stats
from src.ui.webhook.backend import GENERATOR_PAGES, PageBackend
from src.webhook.server import DEFAULT_HOST, DEFAULT_PORT, RequestRecord, WebhookServer, new_token

log = logging.getLogger(__name__)

LAN_HOST = "0.0.0.0"
MAX_LOG = 200


def curl_example(url: str, token: str, page: str = "flow_image", prompt: str = "a red fox in the snow") -> str:
    """A cmd.exe-friendly curl line that submits one job."""
    body = json.dumps({"page": page, "prompt": prompt}).replace('"', '\\"')
    auth = f' -H "Authorization: Bearer {token}"' if token else ""
    return (f'curl -X POST {url}/api/jobs -H "Content-Type: application/json"{auth} -d "{body}"')


class _Relay(QObject):
    """Carries callbacks from server/worker threads to the GUI thread."""

    request = Signal(object)
    stats_changed = Signal()


class StatsView(QWidget):
    COLUMNS = ("wh_stats_provider", "wh_stats_jobs", "wh_stats_done", "wh_stats_failed",
               "wh_stats_stopped", "wh_stats_outputs", "wh_stats_rate")

    def __init__(self, stats: StatsStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.stats = stats
        self.relay = _Relay(self)
        self.relay.stats_changed.connect(self.refresh)
        self._listener = self.relay.stats_changed.emit
        stats.subscribe(self._listener)

        self.since = QLabel()
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(k) for k in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.btn_reset = QPushButton(tr("wh_stats_reset"))
        self.btn_reset.clicked.connect(self.reset)

        top = QHBoxLayout()
        top.addWidget(self.since, 1)
        top.addWidget(self.btn_reset)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        note = QLabel(tr("wh_stats_note"))
        note.setObjectName("StatsNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        rows = self.stats.rows()
        totals = {"name": tr("wh_stats_total"), **self.stats.totals()}
        all_rows = rows + ([totals] if rows else [])
        self.table.setRowCount(len(all_rows))
        for r, row in enumerate(all_rows):
            finished = row["done"] + row["failed"]
            rate = f"{100 * row['done'] / finished:.0f}%" if finished else "-"
            values = [row["name"]] + [str(row[f]) for f in FIELDS] + [rate]
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if row is totals:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(r, c, item)
        since = self.stats.since
        self.since.setText(tr("wh_stats_since", since=since.replace("T", " ")) if since
                           else tr("wh_stats_empty"))

    def value(self, provider_key: str, field: str) -> int:
        for row in self.stats.rows():
            if row["key"] == provider_key:
                return row[field]
        return 0

    def reset(self, confirm: bool = True) -> None:
        if confirm and QMessageBox.question(self, tr("wh_stats_reset"), tr("wh_stats_reset_q")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.stats.reset()

    def shutdown(self) -> None:
        self.stats.unsubscribe(self._listener)


class WebhookPage(QWidget):
    def __init__(self, page_lookup: Callable[[str], Any] | None = None,
                 switch_page: Callable[[str], None] | None = None, store=None,
                 stats: StatsStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        if store is None:
            from src import config
            store = config.settings()
        self.store = store
        self.stats = stats or default_stats()
        self.switch_page = switch_page
        self.backend = PageBackend(page_lookup or (lambda key: None), self.stats,
                                   page_keys=features.visible_pages(GENERATOR_PAGES), parent=self)
        self.server: WebhookServer | None = None
        self._error = ""  # why the last start failed, shown until the next start
        self.relay = _Relay(self)
        self.relay.request.connect(self._log_request)
        self.backend.jobs_submitted.connect(
            lambda page, n: self._append_log(tr("wh_log_submitted", count=n, page=page)))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._server_tab(), tr("wh_tab_server"))
        self.stats_view = StatsView(self.stats)
        self.tabs.addTab(self.stats_view, tr("wh_tab_stats"))

        layout = page_layout(self)
        layout.addLayout(header_row(tr("nav_webhook")))
        layout.addWidget(self.tabs, 1)
        self._update_state()

    # ---- UI ----------------------------------------------------------
    def _server_tab(self) -> QWidget:
        tab = QWidget()
        intro = intro_label(tr("wh_intro"))

        self.status = QLabel()
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(self.store.get("webhook.port", DEFAULT_PORT)))
        self.port.valueChanged.connect(lambda v: self._save("port", int(v)))

        self.token = QLineEdit(str(self.store.get("webhook.token", "")))
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText(tr("wh_token_none"))
        self.token.textChanged.connect(lambda t: self._save("token", t.strip()))
        self.btn_show = QPushButton(tr("wh_token_show"))
        self.btn_show.setCheckable(True)
        self.btn_show.toggled.connect(lambda on: self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.btn_gen = QPushButton(tr("wh_token_generate"))
        self.btn_gen.clicked.connect(lambda: self.token.setText(new_token()))
        token_row = QHBoxLayout()
        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.btn_show)
        token_row.addWidget(self.btn_gen)

        self.lan = QCheckBox(tr("wh_lan"))
        self.lan.setChecked(bool(self.store.get("webhook.lan", False)))
        self.lan.toggled.connect(lambda on: self._save("lan", bool(on)))
        self.autostart = QCheckBox(tr("wh_autostart"))
        self.autostart.setChecked(bool(self.store.get("webhook.autostart", False)))
        self.autostart.toggled.connect(lambda on: self.store.set("webhook.autostart", bool(on)))

        form = QFormLayout()
        form.addRow(tr("wh_status"), self.status)
        form.addRow(tr("wh_port"), self.port)
        form.addRow(tr("wh_token"), token_row)
        form.addRow("", self.lan)
        form.addRow("", self.autostart)

        self.btn_toggle = QPushButton()
        self.btn_toggle.setObjectName("PrimaryButton")
        self.btn_toggle.clicked.connect(self.toggle_server)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_toggle)
        buttons.addStretch(1)

        self.example = QPlainTextEdit()
        self.example.setObjectName("CodeView")
        self.example.setReadOnly(True)
        self.example.setMaximumHeight(100)
        self.btn_copy = QPushButton(tr("wh_copy"))
        self.btn_copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.example.toPlainText()))
        ex_head = QHBoxLayout()
        ex_title = QLabel(tr("wh_example"))
        ex_title.setObjectName("FieldHeading")
        ex_head.addWidget(ex_title, 1)
        ex_head.addWidget(self.btn_copy)

        self.requests = QListWidget()

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(ex_head)
        layout.addWidget(self.example)
        req_title = QLabel(tr("wh_requests"))
        req_title.setObjectName("FieldHeading")
        layout.addWidget(req_title)
        layout.addWidget(self.requests, 1)
        return tab

    def _save(self, name: str, value) -> None:
        self.store.set(f"webhook.{name}", value)
        self._update_state()

    # ---- server ------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.server is not None and self.server.running

    def host(self) -> str:
        return LAN_HOST if self.lan.isChecked() else DEFAULT_HOST

    def start_server(self, port: int | None = None) -> bool:
        """Start listening. ``port=0`` picks a free port (tests)."""
        if self.running:
            return True
        token = self.token.text().strip()
        if self.lan.isChecked() and not token:
            self._error = tr("wh_lan_needs_token")
            self._append_log(self._error)
            self._update_state()
            return False
        server = WebhookServer(self.backend, self.host(), self.port.value() if port is None else port,
                               token, on_request=self.relay.request.emit)
        try:
            server.start()
        except OSError as exc:
            log.error("Webhook API could not start: %s", exc)
            self._error = tr("wh_start_failed", error=str(exc))
            self._append_log(self._error)
            self._update_state()
            return False
        self.server = server
        self._error = ""
        self._append_log(tr("wh_log_started", url=server.url))
        self._update_state()
        return True

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None
            self._append_log(tr("wh_log_stopped"))
        self._update_state()

    def toggle_server(self) -> None:
        if self.running:
            self.stop_server()
        else:
            self.start_server()

    @property
    def url(self) -> str:
        if self.server is not None:
            return self.server.url
        return f"http://{DEFAULT_HOST}:{self.port.value()}"

    def _update_state(self) -> None:
        on = self.running
        self.btn_toggle.setText(tr("wh_stop") if on else tr("wh_start"))
        for w in (self.port, self.token, self.btn_gen, self.lan):
            w.setEnabled(not on)
        if on:
            where = tr("wh_lan_on") if self.server.host == LAN_HOST else ""
            self.status.setText(tr("wh_listening", url=self.server.url) + where)
        else:
            self.status.setText(self._error or tr("wh_stopped"))
        token = self.server.token if on else self.token.text().strip()
        self.example.setPlainText(
            curl_example(self.url, token, self.backend.page_keys[0] if self.backend.page_keys else "flow_image") + "\n\n" + tr("wh_example_status", url=self.url))

    def _log_request(self, rec: RequestRecord) -> None:
        self._append_log(f"{rec.client}  {rec.method} {rec.path}  → {rec.status}")

    def _append_log(self, text: str) -> None:
        self.requests.insertItem(0, f"{datetime.now():%H:%M:%S}  {text}")
        while self.requests.count() > MAX_LOG:
            self.requests.takeItem(self.requests.count() - 1)

    def shutdown(self) -> None:
        self.stop_server()
        self.stats_view.shutdown()
