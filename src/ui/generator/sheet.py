"""The contact sheet: every prompt row as one black frame, decided on with a china marker.

A view over the same PromptTableModel and selection as the queue table, so the two can never
disagree. Approved frames get a hand-drawn red ring, rejected ones a red cross; amber means live.
"""

from __future__ import annotations

import functools
import math
import random
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QWidget

from src import theme
from src.gen.models import Job, JobStatus
from src.gen.progress import clock, progress_view, stage_word
from src.i18n import tr
from src.ui import icons
from src.ui.generator.prompt_model import COL_OUTPUT, VIDEO_EXTS
from src.ui.generator.prompt_table import PromptTable
from src.ui.kit import data_font

REBATE = 22
CACHE_SIZE = 400
FRAME_RATIO = 2 / 3  # the picture area, 3:2 like a 35 mm frame
RING_MS = 260

_images: OrderedDict[tuple[str, float, int], QPixmap] = OrderedDict()


def frame_pixmap(path: Path, width: int, height: int, ratio: float = 1.0) -> QPixmap | None:
    """The picture scaled to fit, cached by file, size and modification time."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), stamp, width * 10000 + height)
    pix = _images.get(key)
    if pix is not None:
        _images.move_to_end(key)
        return pix
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        scale = min(width * ratio / size.width(), height * ratio / size.height(), 1.0)
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
    image = reader.read()
    if image.isNull():
        return None
    pix = QPixmap.fromImage(image)
    pix.setDevicePixelRatio(ratio)
    _images[key] = pix
    while len(_images) > CACHE_SIZE:
        _images.popitem(last=False)
    return pix


def picture_path(job: Job) -> Path | None:
    return job.outputs[0] if job.outputs else job.preview


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


RING_STEPS = 180


def ring_points(rect: QRectF, seed: int) -> list[QPointF]:
    """One hand-drawn lap and a bit, slightly off-round: no two rings on a sheet are the same."""
    rng = random.Random(seed)
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2, rect.height() / 2
    start = rng.uniform(-2.4, -1.2)
    lap = 2 * math.pi * rng.uniform(1.05, 1.13)
    wobble_a, wobble_b = rng.uniform(0.012, 0.03), rng.uniform(0.01, 0.022)
    phase_a, phase_b = rng.uniform(0, 6), rng.uniform(0, 6)
    # a slow lean, one bulge per lap, so the ring is not a perfect ellipse with ripples
    lean, phase_c = rng.uniform(0.012, 0.026), rng.uniform(0, 6)
    drift = rng.uniform(0.012, 0.03)
    points = []
    for i in range(RING_STEPS + 1):
        t = i / RING_STEPS
        a = start + lap * t
        k = 1 + lean * math.sin(a + phase_c) + wobble_a * math.sin(2 * a + phase_a) + wobble_b * math.sin(3 * a + phase_b) - drift * t
        points.append(QPointF(cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    return points


@functools.lru_cache(maxsize=512)
def ring_path(seed: int, w: float, h: float, width: float, count: int) -> QPainterPath:
    """The ring as a filled stroke that swells mid-lap and thins where the pen lands and lifts."""
    points = ring_points(QRectF(5, 5, w - 10, h - 10), seed)[:count]
    left, right = [], []
    for i, pt in enumerate(points):
        a, b = points[max(0, i - 1)], points[min(len(points) - 1, i + 1)]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        n = math.hypot(dx, dy) or 1.0
        t = i / RING_STEPS
        half = width / 2 * (0.4 + 0.6 * math.sin(math.pi * min(1.0, t * 1.15)) ** 0.5)
        ox, oy = -dy / n * half, dx / n * half
        left.append(QPointF(pt.x() + ox, pt.y() + oy))
        right.append(QPointF(pt.x() - ox, pt.y() - oy))
    path = QPainterPath()
    path.addPolygon(QPolygonF(left + right[::-1]))
    path.closeSubpath()
    return path


def draw_ring(p: QPainter, rect: QRectF, seed: int, color: str, width: float = 3.4, progress: float = 1.0) -> None:
    count = max(2, round((RING_STEPS + 1) * progress))
    path = ring_path(seed, round(rect.width()), round(rect.height()), width, count)
    p.save()
    p.translate(rect.topLeft())
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)
    p.restore()


def draw_cross(p: QPainter, rect: QRectF, seed: int, color: str, width: float = 3.4) -> None:
    rng = random.Random(seed)
    inset = 0.2
    x0, x1 = rect.left() + rect.width() * inset, rect.right() - rect.width() * inset
    y0, y1 = rect.top() + rect.height() * inset, rect.bottom() - rect.height() * inset
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for a, b in ((QPointF(x0, y0), QPointF(x1, y1)), (QPointF(x1, y0), QPointF(x0, y1))):
        mid = QPointF((a.x() + b.x()) / 2 + rng.uniform(-6, 6), (a.y() + b.y()) / 2 + rng.uniform(-6, 6))
        path = QPainterPath(a)
        path.quadTo(mid, b)
        p.drawPath(path)


def draw_hatch(p: QPainter, rect: QRectF, color: str) -> None:
    """A failed frame reads as spoiled even without colour vision."""
    tint = QColor(color)
    tint.setAlpha(110)
    pen = QPen(tint, 1)
    p.save()
    p.setClipRect(rect)
    p.setPen(pen)
    step = 10
    h = rect.height()
    x = rect.left() - h
    while x < rect.right():
        p.drawLine(QPointF(x, rect.bottom()), QPointF(x + h, rect.top()))
        x += step
    p.restore()


def edge_state(job: Job) -> str:
    """The word on the frame's edge."""
    if job.review == "approved":
        return tr("gen_state_approved")
    if job.review == "rejected":
        return tr("gen_state_rejected")
    if job.review == "pending_review":
        return tr("gen_state_review")
    if job.review == "regenerating":
        return tr("review_regenerating").upper()
    return tr(f"status_{job.status.value}").upper()


class SheetDelegate(QStyledItemDelegate):
    def __init__(self, view: "SheetView"):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        return self.view.frame_size()

    def paint(self, p: QPainter, option, index) -> None:
        job = index.model().job_at(index.row())
        c = theme.COLORS["dark"]  # a frame is black in both modes
        marks = theme.tokens()
        rect = QRect(option.rect)
        pic = QRectF(rect.left(), rect.top(), rect.width(), rect.height() - REBATE)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(rect, QColor(c["frame"]))

        path = picture_path(job)
        ratio = self.view.devicePixelRatioF()
        drawn = False
        if path is not None and not is_video(path):
            pix = frame_pixmap(path, int(pic.width()), int(pic.height()), ratio)
            if pix is not None:
                w, h = pix.width() / ratio, pix.height() / ratio
                p.drawPixmap(QPointF(pic.center().x() - w / 2, pic.center().y() - h / 2), pix)
                drawn = True
        elif path is not None:
            mark = icons.pixmap("play", c["frame_muted"], 28, ratio)
            p.drawPixmap(QPointF(pic.center().x() - 14, pic.center().y() - 14), mark)
            p.setFont(data_font())
            p.setPen(QColor(c["frame_muted"]))
            p.drawText(pic.adjusted(10, 0, -10, -8), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       p.fontMetrics().elidedText(path.name, Qt.TextElideMode.ElideMiddle, int(pic.width()) - 20))
            drawn = True
        if not drawn:
            self._paint_blank(p, pic, job, c)

        if job.review == "rejected":
            p.fillRect(pic, QColor(0, 0, 0, 130))
            draw_cross(p, pic, job.id, c["marker"])
        elif job.review == "approved":
            draw_ring(p, pic, job.id, c["marker"], progress=self.view.ring_progress(job.id))

        self._paint_rebate(p, rect, job, c)
        if job.status is JobStatus.RUNNING or job.review == "regenerating":
            p.setPen(QPen(QColor(c["live"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(rect).adjusted(1, 1, -1, -1))

        if option.state & QStyle.StateFlag.State_Selected:
            pen = QPen(QColor(marks["text"]), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(rect).adjusted(-2, -2, 2, 2))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(QPen(QColor(marks["border_strong"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(rect).adjusted(-1.5, -1.5, 1.5, 1.5))
        p.restore()

    def _paint_blank(self, p: QPainter, pic: QRectF, job: Job, c: dict) -> None:
        """A frame with no picture yet shows its prompt, or why it failed."""
        failed = job.status is JobStatus.FAILED
        if failed:
            draw_hatch(p, pic, c["failed"])
        font = p.font()
        font.setPixelSize(12)
        p.setFont(font)
        running = job.status is JobStatus.RUNNING
        p.setPen(QColor(c["failed"] if failed else c["frame_text"] if running else c["frame_muted"]))
        text = (job.error or job.prompt) if failed else job.prompt
        area = pic.adjusted(10, 9, -10, -6)
        lines = max(1, int(area.height() // p.fontMetrics().lineSpacing()))
        p.drawText(area, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   _clip(p, text, int(area.width()), lines))

    def _paint_rebate(self, p: QPainter, rect: QRect, job: Job, c: dict) -> None:
        strip = QRectF(rect.left(), rect.bottom() - REBATE + 1, rect.width(), REBATE)
        live = job.status is JobStatus.RUNNING or job.review == "regenerating"
        p.setFont(data_font())
        number = f"{job.index:03d}"
        ident = job.item_id if job.production_id else ""
        if job.outputs and len(job.outputs) > 1:
            ident = f"{ident} +{len(job.outputs) - 1}".strip()
        if job.origin == "agent" and not ident:
            ident = tr("gen_edge_agent")
        state = edge_state(job)
        view = progress_view(job, time.time()) if live else None
        if view is not None and view.percent is not None:
            state = f"{view.percent}%" + (f" 1/{view.tiles}" if view.tiles > 1 else "")
        elif view is not None and view.elapsed_s is not None:
            state = f"{(stage_word(view) or state).upper()} {clock(view.elapsed_s)}"
        elif view is not None and view.stage:
            state = stage_word(view).upper()
        fm = p.fontMetrics()
        p.setPen(QColor(c["live"] if live else c["frame_text"]))
        left = strip.adjusted(8, 0, -8, 0)
        p.drawText(left, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, number)
        state_w = fm.horizontalAdvance(state)
        room = int(left.width()) - fm.horizontalAdvance(number) - state_w - 18
        p.setPen(QColor(c["live"] if live else c["failed"] if job.status is JobStatus.FAILED
                        else c["marker"] if job.review in ("approved", "rejected") else c["frame_muted"]))
        p.drawText(left, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, state)
        if ident and room > 24:
            p.setPen(QColor(c["frame_muted"]))
            mid = left.adjusted(fm.horizontalAdvance(number) + 9, 0, 0, 0)
            p.drawText(mid, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(ident, Qt.TextElideMode.ElideRight, room))
        if view is not None and view.percent is not None:  # only Flow's own number earns a bar
            bar = QRectF(rect.left(), strip.top() - 1, rect.width() * min(1.0, view.percent / 100), 2)
            p.fillRect(bar, QColor(c["live"]))


def _clip(p: QPainter, text: str, width: int, lines: int) -> str:
    """Word-wrapped text cut with an ellipsis at the last line that fits."""
    fm = p.fontMetrics()
    out: list[str] = []
    rest = " ".join(text.split())
    while rest and len(out) < lines:
        cut = len(rest)
        while cut > 0 and fm.horizontalAdvance(rest[:cut]) > width:
            cut = rest.rfind(" ", 0, cut) if " " in rest[:cut] else cut - 1
        cut = max(cut, 1)
        out.append(rest[:cut])
        rest = rest[cut:].lstrip()
    if rest and out:
        out[-1] = fm.elidedText(out[-1] + " " + rest, Qt.TextElideMode.ElideRight, width)
    return "\n".join(out)


FILTERS = {
    "all": lambda job: True,
    "review": lambda job: job.review == "pending_review" or (
        not job.review and job.status is JobStatus.DONE),
    "approved": lambda job: job.review == "approved",
    "rejected": lambda job: job.review == "rejected",
    "failed": lambda job: job.status is JobStatus.FAILED,
}


class SheetView(QListView):
    files_dropped = Signal(list)
    open_requested = Signal(int)     # row
    approve_requested = Signal(list)  # rows
    reject_requested = Signal(list)   # rows
    retry_requested = Signal(list)    # rows
    edit_requested = Signal(int)      # row
    menu_requested = Signal(object)   # global position
    filter_changed = Signal(int)      # visible rows

    def __init__(self, model, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sheet")
        self._width = 240
        self._filter = "all"
        self._rings: dict[int, float] = {}
        self._animations: dict[int, QVariantAnimation] = {}
        self.setModel(model)
        self.setModelColumn(COL_OUTPUT)
        self.setItemDelegate(SheetDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(60)
        self.setUniformItemSizes(True)
        self.setSpacing(7)
        self.setWordWrap(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        # A scrollbar that comes and goes would change the width the columns were fitted to.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.doubleClicked.connect(lambda index: self.open_requested.emit(index.row()))
        for sig in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
            sig.connect(lambda *_: self.apply_filter())

    # ---- layout ------------------------------------------------------
    def _cell_width(self) -> int:
        """``_width`` is the slider's minimum: whole columns fill the viewport, the slack shared out."""
        gap = self.spacing()
        room = self.viewport().width() - gap - 1  # Qt wraps a cell that would touch the edge
        cols = max(1, room // (self._width + gap))
        return max(self._width, room // cols - gap)

    def frame_size(self) -> QSize:
        w = self._cell_width()
        return QSize(w, round(w * FRAME_RATIO) + REBATE)

    def set_frame_width(self, width: int) -> None:
        self._width = width
        self._relayout()

    def _relayout(self) -> None:
        self.setIconSize(self.frame_size())
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self.iconSize() != self.frame_size():
            self._relayout()

    # ---- selection: always whole rows, shared with the queue table ----
    def selectionCommand(self, index, event=None):  # noqa: N802 - Qt override
        return super().selectionCommand(index, event) | QItemSelectionModel.SelectionFlag.Rows

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedRows()})

    # ---- filter ------------------------------------------------------
    def set_filter(self, key: str) -> None:
        self._filter = key
        self.apply_filter()

    def visible_count(self) -> int:
        return sum(1 for r in range(self.model().rowCount()) if not self.isRowHidden(r))

    def apply_filter(self) -> None:
        test = FILTERS[self._filter]
        for row in range(self.model().rowCount()):
            hide = not test(self.model().job_at(row))
            if self.isRowHidden(row) != hide:
                self.setRowHidden(row, hide)
        self.filter_changed.emit(self.visible_count())

    # ---- the ring being drawn ----------------------------------------
    def ring_progress(self, job_id: int) -> float:
        return self._rings.get(job_id, 1.0)

    def draw_ring_on(self, job: Job) -> None:
        """The one authored motion on the sheet: the marker goes round once."""
        if not theme.motion_enabled() or job.id in self._animations:
            return
        anim = QVariantAnimation(self)
        anim.setDuration(RING_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def step(value: float) -> None:
            self._rings[job.id] = value
            self.viewport().update()

        def done() -> None:
            self._rings.pop(job.id, None)
            self._animations.pop(job.id, None)
            self.viewport().update()

        anim.valueChanged.connect(step)
        anim.finished.connect(done)
        self._animations[job.id] = anim
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---- input -------------------------------------------------------
    def _context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        if index.row() not in self.selected_rows():
            self.setCurrentIndex(index)
        self.menu_requested.emit(self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        rows = self.selected_rows()
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if rows:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ctrl or key == Qt.Key.Key_P:
                self.approve_requested.emit(rows)
                return
            if key == Qt.Key.Key_X:
                self.reject_requested.emit(rows)
                return
            if key == Qt.Key.Key_R:
                self.retry_requested.emit(rows)
                return
            if key == Qt.Key.Key_E:
                self.edit_requested.emit(rows[0])
                return
            if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.open_requested.emit(self.currentIndex().row() if self.currentIndex().isValid() else rows[0])
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.acceptProposedAction() if PromptTable._import_paths(event) else event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.acceptProposedAction() if PromptTable._import_paths(event) else event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        paths = PromptTable._import_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


class RunStrip(QWidget):
    """The whole run as one strip of frames: amber is live, so it reads from across the room."""

    row_clicked = Signal(int)

    def __init__(self, model, parent: QWidget | None = None):
        super().__init__(parent)
        self.model_ = model
        self.setFixedHeight(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        for sig in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
            sig.connect(lambda *_: self.update())

    def _color(self, job: Job, c: dict) -> QColor:
        if job.status is JobStatus.RUNNING or job.review == "regenerating":
            return QColor(c["live"])
        if job.review == "approved":
            return QColor(c["marker"])
        if job.review == "rejected":
            return QColor(c["marker"])
        if job.status is JobStatus.FAILED:
            return QColor(c["failed"])
        if job.status is JobStatus.DONE:
            return QColor(c["text"])
        return QColor(c["border_strong"])

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        jobs = self.model_.jobs
        if not jobs:
            return
        c = theme.tokens()
        p = QPainter(self)
        gap = 1 if len(jobs) * 3 < self.width() else 0
        tick = self.width() / len(jobs)
        for i, job in enumerate(jobs):
            p.fillRect(QRectF(i * tick, 0, max(1.0, tick - gap), self.height()), self._color(job, c))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        jobs = self.model_.jobs
        if jobs and self.width():
            self.row_clicked.emit(min(len(jobs) - 1, int(event.position().x() / self.width() * len(jobs))))
