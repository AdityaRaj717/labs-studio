"""Productions page (S5-1): pick two files, see the engine's plan, set the cap, start after a confirm.

Only engine values are shown. Engine calls run off the GUI thread; a Signal brings the reply back.
"""

from __future__ import annotations

import math
import os
import threading
from typing import Callable

from PySide6.QtCore import QFileSystemWatcher, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src import projects
from src.i18n import tr
from src.ui import kit
from src.web.production_actions import ActionError, ProductionActions


def default_cap(estimate: int) -> int:
    """Estimate plus 20% for regenerations, rounded up (owner decision 2)."""
    return math.ceil(estimate * 1.2)


def _mtimes(paths) -> tuple:
    try:
        return tuple(os.stat(p).st_mtime_ns for p in paths)
    except OSError:
        return ()


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldHeading")
    return label


def _data(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setFont(kit.data_font())
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class ProductionsPage(QWidget):
    _back = Signal(object)  # a callable to run on the GUI thread

    def __init__(self, switch_page: Callable[[str], None] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.switch_page = switch_page
        self._actions: ProductionActions | None = None
        self.plan: dict | None = None
        self._checked_paths: tuple[str, str] = ("", "")
        self._checked_mtimes: tuple = ()
        self.busy = False
        self._back.connect(lambda callback: callback())
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(lambda _p: self._update_start())

        outer = kit.page_layout(self)
        outer.addLayout(kit.header_row(tr("nav_productions")))
        outer.addWidget(kit.intro_label(tr("prod_intro")))
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        # 1. Files
        col.addWidget(_heading(tr("prod_files")))
        files = QGridLayout()
        files.setHorizontalSpacing(8)
        self.moodboard_edit, self.prompts_edit = QLineEdit(), QLineEdit()
        for row, (edit, label_key) in enumerate(((self.moodboard_edit, "prod_moodboard"), (self.prompts_edit, "prod_prompts"))):
            edit.setPlaceholderText(tr("prod_pick_file"))
            edit.textChanged.connect(lambda _t: self._update_start())
            browse = QPushButton(tr("prod_browse"))
            browse.clicked.connect(lambda _c=False, e=edit: self._browse(e))
            files.addWidget(QLabel(tr(label_key)), row, 0)
            files.addWidget(edit, row, 1)
            files.addWidget(browse, row, 2)
        col.addLayout(files)
        self.check_btn = QPushButton(tr("prod_check"))
        self.check_btn.clicked.connect(self.check_plan)
        col.addLayout(self._left(self.check_btn))

        # 2. Plan, as the engine returned it
        col.addWidget(_heading(tr("prod_plan")))
        self.summary = _data(tr("prod_no_plan"))
        self.errors_label = _data()
        self.questions_label = _data()
        self.warnings_label = _data()
        self.cast_label = _data()
        for w in (self.summary, self.errors_label, self.questions_label, self.warnings_label, self.cast_label):
            col.addWidget(w)
            w.setVisible(w is self.summary)

        # 3. Settings
        col.addWidget(_heading(tr("prod_settings")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.cap = QSpinBox()
        self.cap.setRange(0, 1_000_000)
        self.cap.setEnabled(False)  # until a plan gives the estimate
        self.cap.setSuffix(" " + tr("prod_credits"))
        self.cap_hint = QLabel()
        self.cap_hint.setObjectName("Hint")
        grid.addWidget(QLabel(tr("prod_cap")), 0, 0)
        grid.addLayout(self._left(self.cap, self.cap_hint), 0, 1)
        self.gate_refs = QCheckBox(tr("prod_gate_refs"))
        self.gate_stills = QCheckBox(tr("prod_gate_stills"))
        for box in (self.gate_refs, self.gate_stills):
            box.setChecked(True)
        grid.addWidget(QLabel(tr("prod_gates")), 1, 0)
        grid.addLayout(self._left(self.gate_refs, self.gate_stills), 1, 1)
        self.ref_mode = QComboBox()
        self.ref_mode.addItem(tr("prod_mode_default"), None)
        self.ref_mode.addItem(tr("prod_mode_ingredient"), "ingredient")
        self.ref_mode.addItem(tr("prod_mode_character"), "character")
        grid.addWidget(QLabel(tr("prod_ref_mode")), 2, 0)
        grid.addLayout(self._left(self.ref_mode), 2, 1)
        self.project = QComboBox()
        grid.addWidget(QLabel(tr("prod_project")), 3, 0)
        grid.addLayout(self._left(self.project), 3, 1)
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        self.cast_confirmed = QCheckBox(tr("prod_cast_confirmed"))
        self.cast_confirmed.toggled.connect(lambda _on: self._update_start())
        col.addWidget(self.cast_confirmed)

        # 4. Start
        self.start_btn = QPushButton(tr("prod_start"))
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.clicked.connect(self.start)
        self.status = QLabel()
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        start_row.addWidget(self.start_btn)
        start_row.addWidget(self.status, 1)  # the reason gets the width, not a narrow wrap
        col.addLayout(start_row)
        col.addStretch(1)
        self._fill_projects()
        self._update_start()

    @staticmethod
    def _left(*widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        return row

    @property
    def actions(self) -> ProductionActions:
        if self._actions is None:
            from src.web.flow_mcp import flow_mcp

            self._actions = ProductionActions(flow_mcp().client)  # this client starts the engine on demand
        return self._actions

    def _act(self, work, done, failed) -> None:
        """Run ``work`` off the GUI thread, then ``done(result)`` or ``failed(error)`` on it."""
        def run() -> None:
            try:
                result = work()
            except ActionError as exc:
                error = exc
                self._back.emit(lambda: failed(error))
            else:
                self._back.emit(lambda: done(result))
        threading.Thread(target=run, name="production-action", daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.check_btn.setEnabled(not busy)
        self._update_start()

    def _browse(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("prod_pick_file"), edit.text(), "Markdown (*.md);;All files (*)")
        if path:
            edit.setText(path)

    def _fill_projects(self) -> None:
        self.project.clear()
        self.project.addItem(tr("prod_project_new"), None)
        active = projects.current()
        if active is not None and active.flow_url:
            self.project.addItem(tr("prod_project_bound", title=active.flow_title or active.flow_url), active.flow_url)
            self.project.setCurrentIndex(1)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._fill_projects()  # the active project may have changed
        self._update_start()

    # ---- check ----------------------------------------------------------
    def paths(self) -> tuple[str, str]:
        return self.moodboard_edit.text().strip(), self.prompts_edit.text().strip()

    def check_plan(self) -> None:
        moodboard, prompts = self.paths()
        if not (moodboard and prompts):
            self.status.setText(tr("prod_need_files"))
            return
        mtimes = _mtimes((moodboard, prompts))  # taken before the read, so an edit during it counts as stale
        self._set_busy(True)
        self.status.setText(tr("prod_checking"))
        self._act(lambda: self.actions.plan(moodboard, prompts),
                  lambda reply: self.show_plan(reply, (moodboard, prompts), mtimes), self._plan_failed)

    def _plan_failed(self, error: ActionError) -> None:
        self._set_busy(False)
        self.show_plan(None)
        self.status.setText(tr("gen_engine_error", message=error.message))

    def show_plan(self, reply: dict | None, paths: tuple[str, str] = ("", ""), mtimes: tuple = ()) -> None:
        """Replace the shown plan with the engine's reply."""
        self.busy = False
        self.check_btn.setEnabled(True)
        self.plan = reply
        self._checked_paths, self._checked_mtimes = paths, mtimes
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        if reply is None:
            for w in (self.errors_label, self.questions_label, self.warnings_label, self.cast_label):
                w.clear()
                w.hide()
            self.summary.setText(tr("prod_no_plan"))
            self._update_start()
            return
        self.watcher.addPaths([p for p in paths if p])
        counts, estimate = reply.get("counts") or {}, reply.get("estimate") or {}
        credits = int(estimate.get("credits") or 0)
        self.summary.setText(tr("prod_summary", refs=counts.get("references", 0), stills=counts.get("stills", 0),
                                animations=counts.get("animations", 0), credits=credits,
                                minutes=estimate.get("eta_minutes", 0), plan_id=reply.get("plan_id") or "-"))

        def where(e: dict) -> str:
            name = os.path.basename(e.get("file") or "") or "-"
            return f"{name}:{e['line']}" if e.get("line") else name
        errors = reply.get("errors") or []
        self.errors_label.setText(tr("prod_errors", count=len(errors)) + "\n" + "\n".join(
            f"  {where(e)}  {e.get('message', '')}" for e in errors) if errors else "")
        questions = reply.get("analysis_needed") or []
        self.questions_label.setText(tr("prod_questions", count=len(questions)) + "\n" + "\n".join(
            f"  {q.get('item', '')}  {q.get('reason', '')}" for q in questions) if questions else "")
        warnings = reply.get("warnings") or []
        self.warnings_label.setText(tr("prod_warnings", count=len(warnings)) + "\n" + "\n".join(
            f"  {where(w)}  {w.get('message', '')}" for w in warnings) if warnings else "")
        cast = reply.get("cast") or []
        self.cast_label.setText(tr("prod_cast", count=len(cast)) + "\n" + "\n".join(
            f"  {c.get('id', '')}  {c.get('name', '')}  ({c.get('kind') or tr('prod_kind_unknown')})" for c in cast) if cast else "")
        for w in (self.errors_label, self.questions_label, self.warnings_label, self.cast_label):
            w.setVisible(bool(w.text()))  # an empty list leaves no gap
        self.cap.setMinimum(credits)  # never below the estimate
        self.cap.setValue(default_cap(credits))
        self.cap.setEnabled(self.has_animations())
        self.cap_hint.setText(tr("prod_cap_hint", credits=credits) if self.has_animations() else tr("prod_cap_stills"))
        self.status.clear()
        self._update_start()

    def has_animations(self) -> bool:
        return bool(self.plan and (self.plan.get("counts") or {}).get("animations"))

    def is_stale(self) -> bool:
        return self.plan is not None and (self.paths() != self._checked_paths or _mtimes(self.paths()) != self._checked_mtimes)

    # ---- start ----------------------------------------------------------
    def blocker(self) -> str:
        """Why Start is off, or '' when it can go."""
        if self.busy:
            return tr("prod_busy")
        if self.plan is None:
            return tr("prod_block_check")
        if self.is_stale():
            return tr("prod_block_stale")
        if self.plan.get("errors") or not self.plan.get("plan_id"):
            return tr("prod_block_errors")
        if self.plan.get("analysis_needed"):
            return tr("prod_block_questions")
        if not self.cast_confirmed.isChecked():
            return tr("prod_block_cast")
        return ""

    def _update_start(self) -> None:
        reason = self.blocker()
        self.start_btn.setEnabled(not reason)
        if reason and not self.busy:
            self.status.setText(reason)
        elif not reason:
            self.status.clear()

    def start(self) -> None:
        self._update_start()
        if self.blocker():
            return
        counts = self.plan.get("counts") or {}
        shots = int(counts.get("stills", 0)) + int(counts.get("animations", 0))
        credits = int((self.plan.get("estimate") or {}).get("credits") or 0)
        cap = max(self.cap.value(), credits) if self.has_animations() else None
        text = tr("prod_confirm", shots=shots, credits=credits, cap=f"{cap} {tr('prod_credits')}" if cap is not None else tr("prod_no_cap"))
        if QMessageBox.question(self, tr("nav_productions"), text) != QMessageBox.StandardButton.Yes:
            return
        args = (self.plan["plan_id"], cap, {"references": self.gate_refs.isChecked(), "stills": self.gate_stills.isChecked()},
                self.ref_mode.currentData(), self.project.currentData(), True)
        target = "flow_video" if self.has_animations() else "flow_image"
        self._set_busy(True)
        self.status.setText(tr("prod_starting"))
        self._act(lambda: self.actions.start(*args), lambda reply: self._started(reply, target), self._start_failed)

    def _started(self, reply: dict, target: str) -> None:
        self._set_busy(False)
        self.status.setText(tr("prod_started", run_id=reply.get("run_id", ""), status=reply.get("status", "")))
        if self.switch_page is not None:
            self.switch_page(target)

    def _start_failed(self, error: ActionError) -> None:
        self._set_busy(False)
        self.status.setText(tr("gen_engine_error", message=error.message))
        QMessageBox.warning(self, tr("nav_productions"), tr("gen_engine_error", message=error.message))
