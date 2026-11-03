"""TakePanel: the selected frame in the Inspector, with its prompt, cast and the marker to hand."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.gen.models import Job, JobStatus
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


class TakePanel(QScrollArea):
    approve_requested = Signal(list)
    reject_requested = Signal(list)
    retry_requested = Signal(list)
    edit_requested = Signal(int)
    view_requested = Signal(int)
    open_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows: list[int] = []
        self.row = -1

        self.preview = QLabel()
        self.preview.setObjectName("TakePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.edge = QLabel()
        self.edge.setObjectName("StatsHeader")
        self.edge.setWordWrap(True)

        self.btn_approve = self._action("gen_approve", "check", "gen_approve_tip",
                                        lambda: self.approve_requested.emit(self.rows), "accent_text")
        self.btn_approve.setObjectName("PrimaryButton")
        self.btn_reject = self._action("gen_reject", "x", "gen_reject_tip",
                                       lambda: self.reject_requested.emit(self.rows))
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

        self.error = self._field("gen_take_error")
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
        layout.addWidget(self.actions_holder)
        for field in (self.error, self.prompt, self.cast, self.scene, self.refs):
            layout.addWidget(field)
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

    def show_rows(self, model, rows: list[int], cast: str = "", scene: str = "") -> None:
        """``cast`` and ``scene``: display names of the single selected frame."""
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
        failed = job.error if job is not None and job.status is JobStatus.FAILED else ""
        self._set(self.error, failed)
        self._set(self.prompt, job.prompt if job is not None else "")
        self._set(self.cast, cast)
        self._set(self.scene, scene)
        self._set(self.refs, "\n".join(p.name for p in job.refs) if job is not None else "")
        if len(jobs) > 1:
            self.edge.setText(tr("gen_take_multi", count=len(jobs)))
        if job is None:
            return
        self.edge.setText("  ".join(p for p in (f"{job.index:03d}", job.item_id, edge_state(job)) if p))
        path = picture_path(job)
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

