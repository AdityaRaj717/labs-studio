"""TakePanel: the selected frame in the Inspector, with its prompt, cast and the marker to hand."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from src.gen.models import Job, JobStatus, Take
from src.gen.provider import SHOT_KEYS, ConfigField
from src.gen.progress import clock, progress_view, stage_word
from src.i18n import tr
from src.ui.generator.sheet import edge_state, frame_pixmap, is_video, picture_path
from src.ui.kit import FlowLayout, set_icon

PREVIEW_HEIGHT = 180


def can_approve(job: Job) -> bool:
    return job.review == "pending_review" or (
        not job.production_id and job.status is JobStatus.DONE and job.review != "approved")


def can_reject(job: Job) -> bool:
    return job.review in ("pending_review", "approved") or (
        not job.production_id and job.status is JobStatus.DONE and job.review != "rejected")


def take_path(take: Take) -> Path | None:
    return Path(take.file) if take.file else None


def take_text(take: Take) -> str:
    """What the engine recorded for one Take; a missing value is left out, never guessed."""
    parts = [f"T{take.n}", tr(f"gen_take_status_{take.status}") if take.status else "",
             tr("gen_take_quoted", credits=take.quoted_credits) if take.quoted_credits else tr("gen_take_quote_unknown")]
    if take.verdict:
        parts.append(tr("gen_take_by", verdict=take.verdict, actor=take.actor or "?") if take.actor else take.verdict)
    if take.at:
        parts.append(take.at.replace("T", " ")[:16])
    lines = ["  ".join(p for p in parts if p)]
    if take.note:
        lines.append(f"“{take.note}”")
    return "\n".join(lines)


def take_can_approve(job: Job, take: Take) -> bool:
    return take.status == "done" and not (job.review == "approved" and job.take == take.n)


def take_can_reject(job: Job, take: Take) -> bool:
    return take.status == "done" and take.verdict != "rejected"


def live_text(job: Job) -> str:
    """Stage, Flow's percent or the elapsed time, attempt and tile note, each only when known."""
    view = progress_view(job, time.time())
    if not view.stage and view.percent is None and view.elapsed_s is None:
        return ""
    head = " ".join(p for p in (stage_word(view),
                                f"{view.percent}%" if view.percent is not None else
                                tr("progress_elapsed", time=clock(view.elapsed_s)) if view.elapsed_s is not None else "") if p)
    lines = [head, tr("progress_from_flow") if view.percent is not None else tr("progress_no_percent")]
    if view.percent is not None and view.tiles > 1:
        lines.append(tr("progress_tiles", tiles=view.tiles))
    if job.attempts > 1:
        lines.append(tr("progress_attempt", n=job.attempts))
    return "\n".join(lines)


class TakePanel(QScrollArea):
    approve_requested = Signal(list)
    reject_requested = Signal(list)
    retry_requested = Signal(list)
    edit_requested = Signal(int)
    view_requested = Signal(int)
    open_requested = Signal(int)
    take_review_requested = Signal(int, int, str, str)  # row, take, approve or reject, note
    frame_changed = Signal(int, str, object)  # row, start_frame or end_frame, Path or None
    shot_override_changed = Signal(list, str, object)  # rows, a SHOT_KEYS key, value or None for the page's

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows: list[int] = []
        self.row = -1
        self.model_ = None
        self.take_n = 0  # the Take the strip shows; 0 is the row's own
        self.frames_enabled = False  # the video page sets this: Flow's Frames mode per shot

        self.preview = QLabel()
        self.preview.setObjectName("TakePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.edge = QLabel()
        self.edge.setObjectName("StatsHeader")
        self.edge.setWordWrap(True)

        self.btn_approve = self._action("gen_approve", "check", "gen_approve_tip",
                                        lambda: self._verdict("approve"), "accent_text")
        self.btn_approve.setObjectName("PrimaryButton")
        self.btn_reject = self._action("gen_reject", "x", "gen_reject_tip",
                                       lambda: self._verdict("reject"))
        self.btn_retry = self._action("gen_retry", "arrow-clockwise", "gen_retry_tip",
                                      lambda: self.retry_requested.emit(self.rows))
        self.btn_edit = self._action("gen_edit", "pencil-simple", "gen_edit_tip",
                                     lambda: self.edit_requested.emit(self.row))
        self.btn_view = self._action("gen_take_view", "eye", "gen_take_view_tip",
                                     lambda: self.view_requested.emit(self.row))
        self.btn_open = self._action("gen_take_open", "arrows-out-simple", "gen_take_open",
                                     lambda: self.open_requested.emit(self.row))
        self.actions_holder = QWidget()
        flow = FlowLayout(self.actions_holder)
        for b in (self.btn_approve, self.btn_reject, self.btn_retry, self.btn_edit, self.btn_view, self.btn_open):
            flow.addWidget(b)

        self.strip_title = QLabel(tr("gen_take_takes"))
        self.strip_title.setObjectName("FieldHeading")
        self.strip = QWidget()
        self.strip_flow = FlowLayout(self.strip)
        self.take_buttons: list[QPushButton] = []
        self.take_info = QLabel()
        self.take_info.setObjectName("Hint")
        self.take_info.setWordWrap(True)
        self.take_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note = QLineEdit()
        self.note.setPlaceholderText(tr("gen_take_note"))
        self.note.setAccessibleName(tr("gen_take_note"))

        self.frames_title = QLabel(tr("gen_take_frames"))
        self.frames_title.setObjectName("FieldHeading")
        self.frames = QWidget()
        frames = QVBoxLayout(self.frames)
        frames.setContentsMargins(0, 0, 0, 0)
        frames.setSpacing(4)
        self.frame_slots = {}
        for which, key in (("start_frame", "gen_take_start_frame"), ("end_frame", "gen_take_end_frame")):
            line = QHBoxLayout()
            line.setSpacing(6)
            name = QLabel()
            name.setObjectName("Hint")
            choose = QPushButton(tr("gen_take_frame_choose"))
            choose.setAccessibleName(f"{tr(key)} {tr('gen_take_frame_choose')}")
            choose.clicked.connect(lambda _c=False, w=which: self._choose_frame(w))
            clear = QPushButton(tr("gen_take_frame_clear"))
            clear.setAccessibleName(f"{tr(key)} {tr('gen_take_frame_clear')}")
            clear.clicked.connect(lambda _c=False, w=which: self.frame_changed.emit(self.row, w, None))
            title = QLabel(tr(key))
            title.setMinimumWidth(36)
            line.addWidget(title)
            line.addWidget(name, 1)
            line.addWidget(choose)
            line.addWidget(clear)
            frames.addLayout(line)
            self.frame_slots[which] = (name, choose, clear)

        self.shot_title = QLabel(tr("gen_take_shot"))
        self.shot_title.setObjectName("FieldHeading")
        self.shot = QWidget()
        self.shot_form = QFormLayout(self.shot)
        self.shot_form.setContentsMargins(0, 0, 0, 0)
        self.shot_fields: list[ConfigField] = []
        self.shot_boxes: dict[str, QComboBox] = {}
        self.page_values = lambda: {}  # the page's own settings, set by GeneratorPage
        self.shot_title.hide()
        self.shot.hide()

        self.error = self._field("gen_take_error")
        self.live = self._field("gen_take_progress")
        self.prompt = self._field("gen_take_prompt")
        self.cast = self._field("gen_take_cast")
        self.scene = self._field("gen_take_scene")
        self.refs = self._field("gen_take_refs")
        self.origin = QLabel(tr("gen_take_origin_agent"))
        self.origin.setObjectName("Hint")

        self.none = QLabel(tr("gen_take_none"))
        self.none.setObjectName("Hint")
        self.none.setWordWrap(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self.none)
        layout.addWidget(self.preview)
        layout.addWidget(self.edge)
        for w in (self.strip_title, self.strip, self.take_info, self.note):
            layout.addWidget(w)
        layout.addWidget(self.actions_holder)
        for field in (self.live, self.error, self.prompt, self.cast, self.scene, self.refs):
            layout.addWidget(field)
        layout.addWidget(self.frames_title)
        layout.addWidget(self.frames)
        layout.addWidget(self.shot_title)
        layout.addWidget(self.shot)
        layout.addWidget(self.origin)
        layout.addStretch(1)
        self.setWidget(body)
        self.show_rows(None, [])

    def _action(self, key: str, icon: str, tip: str, slot, token: str = "text") -> QPushButton:
        b = QPushButton(tr(key))
        set_icon(b, icon, token)
        b.setToolTip(tr(tip))
        b.clicked.connect(lambda _checked=False: slot())
        return b

    def _field(self, key: str) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        title = QLabel(tr(key))
        title.setObjectName("FieldHeading")
        holder.value = QLabel()
        holder.value.setWordWrap(True)
        holder.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(title)
        box.addWidget(holder.value)
        return holder

    def _set(self, field: QWidget, text: str) -> None:
        field.value.setText(text)
        field.setVisible(bool(text))

    # ---- this shot's own settings (S4-5) ------------------------------
    def set_shot_fields(self, fields: list[ConfigField], page_values) -> None:
        """The page's choice fields a shot may set for itself; ``page_values()`` gives the defaults."""
        self.page_values = page_values
        self.shot_fields = [f for f in fields if f.key in SHOT_KEYS and f.kind in ("choice", "int")]
        while self.shot_form.rowCount():
            self.shot_form.removeRow(0)
        self.shot_boxes = {}
        for f in self.shot_fields:
            box = QComboBox()
            box.setAccessibleName(tr(f.label_key))
            box.activated.connect(lambda _i, key=f.key: self._shot_picked(key))
            self.shot_form.addRow(tr(f.label_key), box)
            self.shot_boxes[f.key] = box

    def _shot_options(self, f: ConfigField, values: dict) -> list[str]:
        if f.kind == "int":
            return [str(n) for n in range(int(max(1, f.minimum)), int(f.maximum) + 1)]
        if f.depends_on and f.options_by:
            return [str(o) for o in f.options_by.get(values.get(f.depends_on), f.options)]
        return [str(o) for o in f.options]

    def _label(self, f: ConfigField, value) -> str:
        return tr(f.option_prefix + str(value)) if f.option_prefix else str(value)

    def _shot_picked(self, key: str) -> None:
        value = self.shot_boxes[key].currentData()
        self.shot_override_changed.emit(self.rows, key, value)

    def _show_shot(self, jobs: list[Job]) -> None:
        own = [j for j in jobs if not j.production_id]
        shown = bool(self.shot_fields) and bool(own) and len(own) == len(jobs)
        self.shot_title.setVisible(shown)
        self.shot.setVisible(shown)
        if not shown:
            return
        page = self.page_values()
        first = own[0]
        effective = {**page, **first.overrides}
        editable = all(j.status not in (JobStatus.RUNNING, JobStatus.QUEUED) for j in own)
        for f in self.shot_fields:
            box = self.shot_boxes[f.key]
            box.blockSignals(True)
            box.clear()
            box.addItem(tr("gen_take_shot_page", value=self._label(f, page.get(f.key, f.default))), None)
            for option in self._shot_options(f, effective):
                box.addItem(self._label(f, option), int(option) if f.kind == "int" else option)
            mine = {j.overrides.get(f.key) for j in own}
            pick = mine.pop() if len(mine) == 1 else None
            at = box.findData(int(pick) if f.kind == "int" and pick is not None else pick) if pick is not None else 0
            box.setCurrentIndex(max(0, at))
            box.setEnabled(editable)
            box.blockSignals(False)

    def _choose_frame(self, which: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("gen_take_frames"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.frame_changed.emit(self.row, which, Path(path))

    def _show_frames(self, job: Job | None) -> None:
        shown = self.frames_enabled and job is not None and not job.production_id
        self.frames_title.setVisible(shown)
        self.frames.setVisible(shown)
        if not shown:
            return
        editable = job.status not in (JobStatus.RUNNING, JobStatus.QUEUED)
        for which, (name, choose, clear) in self.frame_slots.items():
            path = getattr(job, which)
            name.setText(path.name if path else tr("gen_take_frame_none"))
            name.setToolTip(str(path) if path else "")
            choose.setEnabled(editable)
            clear.setEnabled(editable and path is not None)

    def _single_take_job(self) -> Job | None:
        """The one selected Production frame that has a Take history, else None."""
        if self.model_ is None or len(self.rows) != 1:
            return None
        job = self.model_.job_at(self.rows[0])
        return job if job.production_id and job.takes else None

    def shown_take(self) -> Take | None:
        job = self._single_take_job()
        if job is None:
            return None
        return next((t for t in job.takes if t.n == self.take_n), job.takes[-1])

    def _verdict(self, action: str) -> None:
        job, take = self._single_take_job(), self.shown_take()
        if job is not None and take is not None:
            self.take_review_requested.emit(self.row, take.n, action, self.note.text())
            self.note.clear()
        elif action == "approve":
            self.approve_requested.emit(self.rows)
        else:
            self.reject_requested.emit(self.rows)

    def select_take(self, n: int) -> None:
        self.take_n = n
        self.show_rows(self.model_, self.rows, *self._names)

    def _build_strip(self, job: Job) -> None:
        for b in self.take_buttons:
            self.strip_flow.removeWidget(b)
            b.deleteLater()
        self.take_buttons = []
        for take in job.takes:
            b = QPushButton(f"T{take.n}")
            b.setObjectName("TakeChip")
            b.setCheckable(True)
            b.setChecked(take.n == self.take_n)
            b.setToolTip(tr("gen_take_take_tip", n=take.n))
            b.setAccessibleName(tr("gen_take_take_tip", n=take.n))
            b.clicked.connect(lambda _checked=False, n=take.n: self.select_take(n))
            self.strip_flow.addWidget(b)
            self.take_buttons.append(b)

    def show_rows(self, model, rows: list[int], cast: str = "", scene: str = "") -> None:
        """``cast`` and ``scene``: display names of the single selected frame."""
        if rows != self.rows:
            self.take_n = 0
            self.note.clear()
        self.model_ = model
        self._names = (cast, scene)
        self.rows = rows
        self.row = rows[0] if rows else -1
        jobs = [model.job_at(r) for r in rows] if model is not None else []
        job = jobs[0] if len(jobs) == 1 else None
        self.none.setVisible(not jobs)
        self.preview.setVisible(job is not None and picture_path(job) is not None)
        self.edge.setVisible(bool(jobs))
        self.actions_holder.setVisible(bool(jobs))
        self.origin.setVisible(job is not None and job.origin == "agent")
        for b in (self.btn_edit, self.btn_view, self.btn_open):
            b.setVisible(job is not None)
        self.btn_approve.setEnabled(any(can_approve(j) for j in jobs))
        self.btn_reject.setEnabled(any(can_reject(j) for j in jobs))
        self.btn_retry.setEnabled(any(j.status is not JobStatus.RUNNING for j in jobs))
        failed = job.error if job is not None and job.status is JobStatus.FAILED else ""
        self._set(self.error, failed)
        self._set(self.live, live_text(job) if job is not None else "")
        self._set(self.prompt, job.prompt if job is not None else "")
        self._set(self.cast, cast)
        self._set(self.scene, scene)
        self._set(self.refs, "\n".join(p.name for p in job.refs) if job is not None else "")
        if len(jobs) > 1:
            self.edge.setText(tr("gen_take_multi", count=len(jobs)))
        take = self.shown_take()
        for w in (self.strip_title, self.strip, self.take_info, self.note):
            w.setVisible(take is not None)
        self.btn_approve.setText(tr("gen_take_approve_n", n=take.n) if take is not None else tr("gen_approve"))
        self.btn_reject.setText(tr("gen_take_reject_n", n=take.n) if take is not None else tr("gen_reject"))
        self._show_frames(job)
        self._show_shot(jobs)
        if job is None:
            return
        self.edge.setText("  ".join(p for p in (f"{job.index:03d}", job.item_id, edge_state(job)) if p))
        path = picture_path(job)
        if take is not None:
            if not any(t.n == self.take_n for t in job.takes):
                self.take_n = job.take if any(t.n == job.take for t in job.takes) else take.n
                take = self.shown_take()
            self._build_strip(job)
            self.btn_approve.setText(tr("gen_take_approve_n", n=take.n))
            self.btn_reject.setText(tr("gen_take_reject_n", n=take.n))
            self.take_info.setText(take_text(take))
            self.btn_approve.setEnabled(take_can_approve(job, take))
            self.btn_reject.setEnabled(take_can_reject(job, take))
            if take.prompt:
                self._set(self.prompt, take.prompt)
            if take.refs_used:
                self._set(self.refs, "\n".join(Path(r).name for r in take.refs_used))
            path = take_path(take) or (path if take.n == job.take else None)
        self.btn_view.setEnabled(path is not None)
        self.btn_open.setEnabled(path is not None)
        self.btn_edit.setEnabled(job.status is not JobStatus.RUNNING)
        self.preview.clear()
        if path is None:
            self.preview.setText(tr("gen_viewer_nothing"))
        elif is_video(path):
            self.preview.setText(path.name)
        else:
            width = max(1, self.viewport().width() - 24)
            pix = frame_pixmap(path, width, PREVIEW_HEIGHT, self.devicePixelRatioF())
            if pix is not None:
                self.preview.setPixmap(pix)
            else:
                self.preview.setText(tr("gen_viewer_nothing"))

