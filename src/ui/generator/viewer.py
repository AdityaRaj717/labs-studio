"""TakeViewer: one frame filling the page, on black, with the marker to hand. Space from the sheet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from src import theme
from src.gen.models import Job, JobStatus, Take
from src.i18n import tr
from src.ui import icons
from src.ui.generator.sheet import draw_flag, edge_state, is_video
from src.ui.generator.take_panel import take_can_approve, take_can_reject
from src.ui.kit import IconButton, data_font


class _Canvas(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(120)
        self.job: Job | None = None
        self.pix: QPixmap | None = None
        self.message = ""
        self.verdict = ""
        self.label = ""

    def show_job(self, job: Job | None, path: Path | None, verdict: str | None = None, label: str = "") -> None:
        """``verdict``: the shown Take's own mark, when it is not the row's."""
        self.job = job
        self.verdict = (job.review if job is not None else "") if verdict is None else verdict
        self.label = label
        self.pix = None
        self.message = ""
        if path is None:
            self.message = tr("gen_viewer_nothing")
        elif is_video(path):
            self.message = tr("gen_viewer_video")
        else:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                self.message = tr("gen_viewer_nothing")
            else:
                self.pix = QPixmap.fromImage(image)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        c = theme.COLORS["dark"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(c["frame"]))
        area = QRectF(self.rect())
        if self.pix is not None:
            scale = min(area.width() / self.pix.width(), area.height() / self.pix.height())
            w, h = self.pix.width() * scale, self.pix.height() * scale
            area = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
            p.drawPixmap(area, self.pix, QRectF(self.pix.rect()))
        else:
            p.setPen(QColor(c["frame_muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        mark = QRectF(self.rect().right() - 28, 10, 16, 16)  # the decision, as on the sheet's cell
        if self.job is not None and self.verdict == "approved":
            draw_flag(p, mark, c["accent"])
        elif self.job is not None and self.verdict == "rejected":
            p.drawPixmap(mark.topLeft(), icons.pixmap("x", c["accent"], 16, self.devicePixelRatioF()))
        if self.label:
            p.setFont(data_font())
            p.setPen(QColor(c["frame_text"]))
            p.drawText(QRectF(self.rect()).adjusted(10, 8, -10, -8),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.label)
        p.end()


class TakeViewer(QWidget):
    closed = Signal()
    row_changed = Signal(int)
    approve_requested = Signal(list)
    reject_requested = Signal(list)
    take_review_requested = Signal(int, int, str, str)  # row, take, approve or reject, note
    retry_requested = Signal(list)
    edit_requested = Signal(int)
    open_requested = Signal(object)  # path

    def __init__(self, model, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Viewer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.model_ = model
        self.row = -1
        self.output = 0
        self.take_n = 0  # the Take shown on the left; 0 is the row's own
        self.compare_n = 0  # the Take beside it while comparing; 0 is off
        self.rows: list[int] = []

        ink = theme.COLORS["dark"]["frame_text"]
        self.btn_back = QPushButton(tr("gen_viewer_back"))
        self.btn_back.setIcon(icons.icon("caret-left", ink))
        self.btn_back.clicked.connect(self.closed.emit)
        self.edge = QLabel()
        self.edge.setObjectName("ViewerText")
        self.btn_prev = self._nav("caret-left", "gen_viewer_prev", lambda: self.step(-1))
        self.btn_next = self._nav("caret-right", "gen_viewer_next", lambda: self.step(1))
        self.btn_prev_take = self._nav("caret-up", "gen_viewer_prev_take", lambda: self.step_output(-1))
        self.btn_next_take = self._nav("caret-down", "gen_viewer_next_take", lambda: self.step_output(1))
        top = QHBoxLayout()
        top.setContentsMargins(10, 8, 44, 8)
        top.setSpacing(6)
        top.addWidget(self.btn_back)
        top.addSpacing(10)
        top.addWidget(self.edge, 1)
        self.btn_compare = QPushButton(tr("gen_viewer_compare"))
        self.btn_compare.setIcon(icons.icon("squares-four", ink))
        self.btn_compare.setToolTip(tr("gen_viewer_compare_tip"))
        self.btn_compare.setCheckable(True)
        self.btn_compare.clicked.connect(lambda _checked=False: self.toggle_compare())
        top.addWidget(self.btn_compare)
        for b in (self.btn_prev_take, self.btn_next_take, self.btn_prev, self.btn_next):
            top.addWidget(b)

        self.canvas = _Canvas()
        self.canvas_b = _Canvas()
        self.canvas_b.hide()
        pictures = QHBoxLayout()
        pictures.setContentsMargins(0, 0, 0, 0)
        pictures.setSpacing(2)
        pictures.addWidget(self.canvas, 1)
        pictures.addWidget(self.canvas_b, 1)
        self.prompt = QLabel()
        self.prompt.setObjectName("ViewerPrompt")
        self.prompt.setWordWrap(True)
        self.prompt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.btn_approve = self._action("gen_approve", "check", lambda: self.verdict("approve"))
        self.btn_approve.setObjectName("PrimaryButton")
        self.btn_approve.setToolTip(tr("gen_approve_tip"))
        self.btn_reject = self._action("gen_reject", "x", lambda: self.verdict("reject"))
        self.btn_reject.setToolTip(tr("gen_reject_tip"))
        self.btn_retry = self._action("gen_retry", "arrow-clockwise", lambda: self.retry_requested.emit([self.row]))
        self.btn_retry.setToolTip(tr("gen_retry_tip"))
        self.btn_edit = self._action("gen_edit", "pencil-simple", lambda: self.edit_requested.emit(self.row))
        self.btn_edit.setToolTip(tr("gen_edit_tip"))
        self.btn_open = self._action("gen_take_open", "arrows-out-simple", self._open_file)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 8, 10, 10)
        bottom.setSpacing(6)
        bottom.addWidget(self.prompt, 1)
        bottom.addSpacing(16)
        for b in (self.btn_open, self.btn_edit, self.btn_retry, self.btn_reject, self.btn_approve):
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            bottom.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addLayout(pictures, 1)
        layout.addLayout(bottom)
        model.dataChanged.connect(lambda *_: self.isVisible() and self.refresh())

    def _nav(self, name: str, tip: str, slot) -> IconButton:
        b = IconButton(name, tr(tip), slot)
        b.setIcon(icons.icon(name, theme.COLORS["dark"]["frame_text"]))
        b.color_token = "frame_text"  # the viewer is black in both modes
        return b

    def _action(self, key: str, name: str, slot) -> QPushButton:
        b = QPushButton(tr(key))
        b.setIcon(icons.icon(name, theme.COLORS["dark"]["frame_text"]))
        b.clicked.connect(lambda _checked=False: slot())
        return b

    # ---- state -------------------------------------------------------
    def open_row(self, row: int, rows: list[int]) -> None:
        """``rows``: what Left and Right walk through, the frames the sheet currently shows."""
        self.rows = rows or [row]
        self.row = row
        self.output = 0
        self.take_n = self.compare_n = 0
        self.refresh()
        self.setFocus()

    def job(self) -> Job | None:
        if 0 <= self.row < self.model_.rowCount():
            return self.model_.job_at(self.row)
        return None

    def take(self, job: Job, n: int | None = None) -> Take | None:
        """The shown Take of a Production row, or None for a row without a history."""
        if not job.takes:
            return None
        n = self.take_n if n is None else n
        return next((t for t in job.takes if t.n == n), None) or next(
            (t for t in job.takes if t.n == job.take), job.takes[-1])

    def _take_path(self, job: Job, take: Take) -> Path | None:
        if take.file:
            return Path(take.file)
        return self._output_path(job) if take.n == job.take else None

    def _path(self, job: Job) -> Path | None:
        take = self.take(job)
        if take is not None:
            return self._take_path(job, take)
        return self._output_path(job)

    def _output_path(self, job: Job) -> Path | None:
        if job.outputs:
            return job.outputs[min(self.output, len(job.outputs) - 1)]
        return job.preview

    def refresh(self) -> None:
        job = self.job()
        if job is None:
            self.closed.emit()
            return
        path = self._path(job)
        take = self.take(job)
        if take is None:
            self.canvas.show_job(job, path)
        else:
            self.take_n = take.n
            self.canvas.show_job(job, path, take.verdict, f"T{take.n}")
        other = self.take(job, self.compare_n) if take is not None and self.compare_n else None
        self.canvas_b.setVisible(other is not None)
        self.btn_compare.setChecked(other is not None)
        self.btn_compare.setVisible(len(job.takes) > 1)
        if other is not None:
            self.canvas_b.show_job(job, self._take_path(job, other), other.verdict, f"T{other.n}")
        pos = self.rows.index(self.row) + 1 if self.row in self.rows else 1
        parts = [f"{job.index:03d}", job.item_id, edge_state(job), f"{pos}/{len(self.rows)}"]
        if take is not None and len(job.takes) > 1:
            parts.append(f"T{take.n}/{len(job.takes)}")
        elif len(job.outputs) > 1:
            parts.append(f"{min(self.output, len(job.outputs) - 1) + 1}/{len(job.outputs)} files")
        self.edge.setText("  ".join(p for p in parts if p))
        self.prompt.setText((job.error + "\n" if job.status is JobStatus.FAILED and job.error else "") + job.prompt)
        self.btn_approve.setEnabled(job.review == "pending_review" or (
            not job.production_id and job.status is JobStatus.DONE and job.review != "approved"))
        self.btn_reject.setEnabled(job.review in ("pending_review", "approved") or (
            not job.production_id and job.status is JobStatus.DONE and job.review != "rejected"))
        if take is not None and job.production_id:
            self.btn_approve.setEnabled(take_can_approve(job, take))
            self.btn_reject.setEnabled(take_can_reject(job, take))
        self.btn_open.setEnabled(path is not None)
        many = len(job.takes) > 1 or (not job.takes and len(job.outputs) > 1)
        self.btn_prev_take.setToolTip(tr("gen_viewer_prev_take_n" if job.takes else "gen_viewer_prev_take"))
        self.btn_next_take.setToolTip(tr("gen_viewer_next_take_n" if job.takes else "gen_viewer_next_take"))
        self.btn_prev_take.setVisible(many)
        self.btn_next_take.setVisible(many)
        self.btn_prev.setEnabled(len(self.rows) > 1)
        self.btn_next.setEnabled(len(self.rows) > 1)
        self.row_changed.emit(self.row)

    def step(self, delta: int) -> None:
        if self.row not in self.rows or len(self.rows) < 2:
            return
        self.row = self.rows[(self.rows.index(self.row) + delta) % len(self.rows)]
        self.output = 0
        self.take_n = self.compare_n = 0
        self.refresh()

    def verdict(self, action: str) -> None:
        """A Production row with a history is decided on the shown Take; anything else on the row."""
        job = self.job()
        take = self.take(job) if job is not None and job.production_id else None
        if take is not None:
            self.take_review_requested.emit(self.row, take.n, action, "")
        elif action == "approve":
            self.approve_requested.emit([self.row])
        else:
            self.reject_requested.emit([self.row])

    def toggle_compare(self) -> None:
        """Two-up: the shown Take beside the approved one, or beside the one before it."""
        job = self.job()
        if job is None or len(job.takes) < 2 or self.compare_n:
            self.compare_n = 0
        else:
            shown = self.take(job).n
            approved = job.take if job.review == "approved" and job.take != shown else 0
            others = [t.n for t in job.takes if t.n != shown]
            self.compare_n = approved or max((n for n in others if n < shown), default=others[-1])
        self.refresh()

    def step_output(self, delta: int) -> None:
        job = self.job()
        if job is not None and len(job.takes) > 1:
            ns = [t.n for t in job.takes]
            self.take_n = ns[(ns.index(self.take(job).n) + delta) % len(ns)]
            if self.take_n == self.compare_n:
                self.compare_n = 0
            self.refresh()
        elif job is not None and len(job.outputs) > 1:
            self.output = (self.output + delta) % len(job.outputs)
            self.refresh()

    def _open_file(self) -> None:
        job = self.job()
        path = self._path(job) if job is not None else None
        if path is not None:
            self.open_requested.emit(path)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.closed.emit()
        elif key == Qt.Key.Key_Left:
            self.step(-1)
        elif key == Qt.Key.Key_Right:
            self.step(1)
        elif key == Qt.Key.Key_BracketLeft:
            self.step_output(-1)
        elif key == Qt.Key.Key_BracketRight:
            self.step_output(1)
        elif key == Qt.Key.Key_P or (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                                     and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.verdict("approve")
        elif key == Qt.Key.Key_X:
            self.verdict("reject")
        elif key == Qt.Key.Key_R:
            self.retry_requested.emit([self.row])
        elif key == Qt.Key.Key_C:
            self.toggle_compare()
        elif key == Qt.Key.Key_E:
            self.edit_requested.emit(self.row)
        else:
            super().keyPressEvent(event)

