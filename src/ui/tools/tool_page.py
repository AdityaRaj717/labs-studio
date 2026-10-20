"""ToolPage: file list + options + Start/Stop for one external-binary tool.

Reuses the Phase 2 pieces: ``JobQueue`` runs one job per input file on worker
threads, ``QueueBridge`` brings updates to the GUI thread, ``ConfigPanel``
holds the options (saved at ``pages.<page_key>.*``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src import config, theme
from src.gen.models import RETRYABLE_STATUSES, Job, JobStatus
from src.gen.output import default_save_dir
from src.gen.provider import ConfigField
from src.gen.queue import JobQueue, QueueSettings
from src.i18n import tr
from src.tools.tasks import ToolProvider, missing_message
from src.ui.generator.config_panel import ConfigPanel
from src.ui.generator.prompt_model import STATUS_COLORS
from src.ui.generator.queue_bridge import QueueBridge

log = logging.getLogger(__name__)

COL_FILE, COL_STATUS, COL_PROGRESS, COL_OUTPUT = range(4)
COLUMN_KEYS = ("tools_col_file", "tools_col_status", "tools_col_progress", "tools_col_output")

# Shown on every tool page: how many files run at once and where results go.
COMMON_TOOL_FIELDS = [
    ConfigField("threads", "gen_threads", "int", 1, minimum=1, maximum=4),
    ConfigField("save_dir", "gen_save_dir", "folder", ""),
]


class ToolPage(QWidget):
    def __init__(self, page_key: str, provider: ToolProvider, fields: list[ConfigField],
                 exts: set[str], title: str = "", intro: str = "",
                 visible_when: dict[str, tuple[str, tuple]] | None = None,
                 store=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.page_key = page_key
        self.provider = provider
        self.exts = {e.lower() for e in exts}
        self.store = store if store is not None else config.settings()
        self.visible_when = visible_when or {}
        self.jobs: list[Job] = []
        self._rows: dict[int, int] = {}  # job id -> row
        self.row_actions: list[Callable[[], None]] = []

        self.bridge = QueueBridge(self)
        self.bridge.job_updated.connect(self._on_job_updated)
        self.bridge.finished.connect(self._on_finished)
        self.queue = JobQueue(provider, provider.take_outputs,
                              on_update=self.bridge.on_update, on_finished=self.bridge.on_finished)

        # Left: options.
        self.config_panel = ConfigPanel(page_key, fields + COMMON_TOOL_FIELDS, store=self.store)
        self.config_panel.changed.connect(lambda *_: self._apply_visibility())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.config_panel)
        scroll.setMinimumWidth(320)
        scroll.setMaximumWidth(420)

        # Right: banner, toolbar, table.
        self.missing_label = QLabel()
        self.missing_label.setObjectName("DemoBanner")
        self.missing_label.setWordWrap(True)
        self.missing_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.missing_label.hide()

        self.btn_add = self._button("tools_add_files", self.add_dialog)
        self.btn_add_folder = self._button("tools_add_folder", self.add_folder_dialog)
        self.btn_remove = self._button("gen_remove", self.remove_selected)
        self.btn_clear = self._button("gen_clear", self.clear)
        self.btn_start = self._button("gen_start", self.start)
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_stop = self._button("gen_stop", self.stop)
        self.btn_folder = self._button("gen_open_folder", self.open_output_folder)
        self.toolbar = QHBoxLayout()
        for b in (self.btn_add, self.btn_add_folder, self.btn_remove, self.btn_clear):
            self.toolbar.addWidget(b)
        self.toolbar.addStretch(1)
        for b in (self.btn_start, self.btn_stop, self.btn_folder):
            self.toolbar.addWidget(b)

        self.table = QTableWidget(0, len(COLUMN_KEYS))
        self.table.setHorizontalHeaderLabels([tr(k) for k in COLUMN_KEYS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_OUTPUT, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_STATUS, 90)
        self.table.setColumnWidth(COL_PROGRESS, 140)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._update_controls)

        self.hint = QLabel(tr("tools_drop_hint"))
        self.hint.setObjectName("PageBody")
        self.hint.setWordWrap(True)

        right = QVBoxLayout()
        if intro:
            intro_label = QLabel(intro)
            intro_label.setObjectName("PageBody")
            intro_label.setWordWrap(True)
            right.addWidget(intro_label)
        right.addWidget(self.missing_label)
        right.addLayout(self.toolbar)
        right.addWidget(self.table, 1)
        right.addWidget(self.hint)

        body = QHBoxLayout()
        body.addWidget(scroll)
        body.addLayout(right, 1)

        layout = QVBoxLayout(self)
        if title:
            layout.setContentsMargins(32, 28, 32, 28)
            title_label = QLabel(title)
            title_label.setObjectName("PageTitle")
            layout.addWidget(title_label)
        else:
            layout.setContentsMargins(8, 12, 8, 8)
        layout.addLayout(body, 1)

        self.setAcceptDrops(True)
        self._apply_visibility()
        self.refresh_binaries()

    def _button(self, key: str, slot) -> QPushButton:
        b = QPushButton(tr(key))
        b.clicked.connect(slot)
        return b

    # ---- binaries -----------------------------------------------------
    def refresh_binaries(self) -> list[str]:
        """Re-check PATH / Settings; show the missing-binary message."""
        missing = self.provider.missing()
        if missing:
            self.missing_label.setText(missing_message(missing))
            self.missing_label.show()
        else:
            self.missing_label.hide()
        self._missing = missing
        self._update_controls()
        return missing

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self.queue.is_running():
            self.refresh_binaries()

    # ---- options ------------------------------------------------------
    def _apply_visibility(self) -> None:
        form = self.config_panel.layout()
        for key, (mode_key, values) in self.visible_when.items():
            editor = self.config_panel.editors.get(key)
            if editor is not None:
                form.setRowVisible(editor, self.config_panel.value(mode_key) in values)

    def options(self) -> dict:
        opts = self.config_panel.values()
        opts["out_dir"] = str(self._base_dir())
        return opts

    def _base_dir(self) -> Path:
        save_dir = self.config_panel.value("save_dir")
        return Path(save_dir) if save_dir else default_save_dir(self.page_key)

    # ---- files --------------------------------------------------------
    def add_files(self, paths: list[Path | str]) -> int:
        known = {str(Path(j.refs[0]).resolve()).lower() for j in self.jobs}
        added = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                added += self.add_files(sorted(p for p in path.iterdir() if p.is_file()))
                continue
            if path.suffix.lower() not in self.exts or not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in known:
                continue
            known.add(key)
            job = Job(prompt=path.name, index=len(self.jobs) + 1, refs=[path])
            self.jobs.append(job)
            self._append_row(job)
            added += 1
        self._update_controls()
        return added

    def add_dialog(self) -> None:
        pattern = " ".join(f"*{e}" for e in sorted(self.exts))
        files, _ = QFileDialog.getOpenFileNames(self, tr("tools_add_files"), "",
                                                f"{tr('tools_supported')} ({pattern})")
        if files:
            self.add_files(files)

    def add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("tools_add_folder"))
        if folder:
            self.add_files([folder])

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def remove_selected(self) -> None:
        if self.queue.is_running():
            return
        for row in reversed(self.selected_rows()):
            self.queue.forget([self.jobs.pop(row)])
        self._rebuild()

    def clear(self) -> None:
        if self.queue.is_running():
            return
        self.queue.forget(self.jobs)
        self.jobs.clear()
        self._rebuild()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.queue.is_running():
            return
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    # ---- table --------------------------------------------------------
    def _append_row(self, job: Job) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[job.id] = row
        name = QTableWidgetItem(job.prompt)
        name.setToolTip(str(job.refs[0]))
        self.table.setItem(row, COL_FILE, name)
        self.table.setItem(row, COL_STATUS, QTableWidgetItem())
        self.table.setItem(row, COL_OUTPUT, QTableWidgetItem())
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(True)
        c = theme.COLORS[theme.current_mode()]
        bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {c['border']}; border-radius: 3px; "
            f"background: {c['input_bg']}; text-align: center; }}"
            f"QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}")
        self.table.setCellWidget(row, COL_PROGRESS, bar)
        self._refresh_row(job)

    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        self._rows.clear()
        for i, job in enumerate(self.jobs, 1):
            job.index = i
            self._append_row(job)
        self._update_controls()

    def _refresh_row(self, job: Job) -> None:
        row = self._rows.get(job.id)
        if row is None:
            return
        status = self.table.item(row, COL_STATUS)
        status.setText(tr(f"status_{job.status.value}"))
        status.setForeground(QColor(STATUS_COLORS[job.status]))
        bar = self.table.cellWidget(row, COL_PROGRESS)
        bar.setValue(int(job.progress * 1000))
        bar.setFormat(f"{job.progress * 100:.0f}%")
        out = self.table.item(row, COL_OUTPUT)
        if job.status is JobStatus.FAILED:
            out.setText(job.error)
            out.setToolTip(job.error)
        elif job.outputs:
            first = job.outputs[0]
            text = first.name if len(job.outputs) == 1 else tr(
                "tools_n_files", n=len(job.outputs), folder=first.parent.name)
            out.setText(text)
            out.setToolTip(str(first if len(job.outputs) == 1 else first.parent))
        else:
            out.setText("")
            out.setToolTip("")

    def _on_job_updated(self, job_id: int) -> None:
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is not None:
            self._refresh_row(job)

    def _on_finished(self) -> None:
        stats = self.queue.stats()
        log.info("%s finished: %d done, %d failed", self.page_key, stats.get("done", 0),
                 stats.get("failed", 0))
        self._update_controls()

    def _on_double_click(self, row: int, _col: int) -> None:
        job = self.jobs[row]
        if job.outputs:
            target = job.outputs[0] if len(job.outputs) == 1 else job.outputs[0].parent
            self._open(target)

    # ---- run ----------------------------------------------------------
    def start(self) -> int:
        if self.queue.is_running():
            return 0
        if self.refresh_binaries():
            return 0
        todo = [j for j in self.jobs if j.status in RETRYABLE_STATUSES]
        if not todo:
            return 0
        threads = int(self.config_panel.value("threads"))
        queued = self.queue.start(todo, self.options(), QueueSettings(threads=threads, max_retries=0))
        log.info("%s started: %d file(s) -> %s", self.page_key, queued, self._base_dir())
        self._update_controls()
        return queued

    def stop(self) -> None:
        self.queue.stop()
        self._update_controls()

    def _update_controls(self) -> None:
        running = self.queue.is_running()
        has_rows = bool(self.jobs)
        todo = any(j.status is not JobStatus.DONE for j in self.jobs)
        self.btn_start.setEnabled(not running and has_rows and todo and not getattr(self, "_missing", []))
        self.btn_stop.setEnabled(running)
        for b in (self.btn_add, self.btn_add_folder, self.btn_clear):
            b.setEnabled(not running)
        self.btn_remove.setEnabled(not running and bool(self.selected_rows()))
        self.config_panel.setEnabled(not running)
        self.hint.setVisible(not has_rows)

    # ---- output -------------------------------------------------------
    @staticmethod
    def _open(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_output_folder(self) -> None:
        folder = self._base_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._open(folder)

    def shutdown(self) -> None:
        if self.queue.is_running():
            self.queue.stop()
            self.queue.wait(5)
