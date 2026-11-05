"""The contact sheet: every prompt row as one grey cell, graded like a Lightroom grid.

A view over the same PromptTableModel and selection as the queue table, so the two can never
disagree. A flag in the accent marks the decision, stars and a colour label are the owner's own
grade; amber means live.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QWidget

from src import theme
from src.gen.models import Job, JobStatus
from src.gen.progress import clock, progress_view, shown_percent, stage_word
from src.i18n import tr
from src.ui import icons
from src.ui.generator.prompt_model import COL_OUTPUT, VIDEO_EXTS
from src.ui.generator.prompt_table import PromptTable
from src.ui.generator.thumbs import service as thumbs
from src.ui.kit import data_font, ui_font

FRAME_RATIO = 2 / 3  # the picture area, 3:2 like a 35 mm frame
PAD = 8
INDEX_BAND = 14  # compact: room for the 11px index above the picture, so it never sits on it
BOTTOM_ROW = 22
TOP_ROW = 20
DENSITIES = (1, 2, 0)  # J walks compact -> expanded -> picture -> compact
LABELS = ("red", "yellow", "green", "blue", "purple")
LABEL_KEYS = {Qt.Key.Key_6: "red", Qt.Key.Key_7: "yellow", Qt.Key.Key_8: "green", Qt.Key.Key_9: "blue"}


def picture_path(job: Job) -> Path | None:
    return job.outputs[0] if job.outputs else job.preview


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def draw_hatch(p: QPainter, rect: QRectF, color: str) -> None:
    """A failed frame reads as spoiled even without colour vision."""
    tint = QColor(color)
    tint.setAlpha(70)
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


def star_polygon(center: QPointF, radius: float) -> QPolygonF:
    pts = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(center.x() + r * math.cos(a), center.y() + r * math.sin(a)))
    return QPolygonF(pts)


def star_icon(color: str, size: int = 12, ratio: float = 2.0) -> QIcon:
    """The sheet's drawn star as a button icon, so stars look the same everywhere."""
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(star_polygon(QPointF(size / 2, size / 2 + 0.5), size / 2))
    p.end()
    return QIcon(pix)


def draw_flag(p: QPainter, rect: QRectF, color: str) -> None:
    """A filled flag: the approved mark, in the accent."""
    x, y, h = rect.left() + 1, rect.top(), rect.height()
    p.fillRect(QRectF(x, y, 1.5, h), QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([QPointF(x + 1.5, y), QPointF(x + h * 0.9, y + h * 0.28),
                             QPointF(x + 1.5, y + h * 0.56)]))


def take_badge(job: Job) -> str:
    """``T2/3`` once an Item has more than one Take: the shown one of how many."""
    total = max(job.latest_take, len(job.takes))
    return f"T{job.take}/{total}" if job.production_id and total > 1 and job.take else ""


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


def is_live(job: Job) -> bool:
    return job.status is JobStatus.RUNNING or job.review == "regenerating"


def cell_state(job: Job, now: float | None = None) -> tuple[str, str, int | None]:
    """The cell's state text, its colour token, and the percent shown (None unless live and known).

    No word where the flag or x already says the decision, and none for a plain finished frame."""
    live = is_live(job)
    if job.review in ("approved", "rejected") or (job.status is JobStatus.DONE and not job.review):
        state = ""
    elif job.review == "pending_review":
        state = tr("gen_cell_review")
    elif job.review == "regenerating":
        state = tr("review_regenerating")
    else:
        state = tr(f"status_{job.status.value}")
    if job.stale and not live:
        state = f"{tr('gen_cell_stale')}, {state.lower()}" if state else tr("gen_cell_stale")
    view = progress_view(job, now if now is not None else time.time()) if live else None
    percent = shown_percent(job, view) if view is not None else None  # the queue's rule, so both agree
    if percent is not None:
        state = f"{percent}%" + (f" 1/{view.tiles}" if view.tiles > 1 else "")
    elif view is not None and view.elapsed_s is not None:
        state = f"{stage_word(view) or state} {clock(view.elapsed_s)}"
    elif view is not None and view.stage:
        state = stage_word(view)
    token = "live" if live else "failed" if job.status is JobStatus.FAILED else "text_muted"
    return state, token, percent


def ident_text(job: Job) -> str:
    ident = job.item_id if job.production_id else ""
    if job.outputs and len(job.outputs) > 1:
        ident = f"{ident} +{len(job.outputs) - 1}".strip()
    badge = take_badge(job)
    if badge:
        ident = f"{ident} {badge}".strip()
    if job.origin == "agent" and not ident:
        ident = tr("gen_edge_agent")
    return ident


class SheetDelegate(QStyledItemDelegate):
    def __init__(self, view: "SheetView"):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        return self.view.frame_size()

    def paint(self, p: QPainter, option, index) -> None:
        job = index.model().job_at(index.row())
        c = theme.tokens()
        rect = QRect(option.rect)
        density = self.view.density
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        pic = self.view.picture_rect(QRectF(rect))
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(rect, QColor(c["cell_selected" if selected else "cell_hover" if hovered else "cell"]))

        path = picture_path(job)
        ratio = self.view.devicePixelRatioF()
        drawn = False
        if path is not None and not is_video(path):
            pix = thumbs().get(path, int(pic.width()), int(pic.height()), ratio)
            if pix is not None:
                size = pix.deviceIndependentSize()
                w, h = size.width(), size.height()
                if job.review == "rejected":
                    p.setOpacity(0.45)
                p.drawPixmap(QPointF(pic.center().x() - w / 2, pic.center().y() - h / 2), pix)
                p.setOpacity(1.0)
            drawn = True  # still decoding: keep the cell plain rather than flash the prompt (no stat per paint)
        elif path is not None:
            mark = icons.pixmap("play", c["text_muted"], 28, ratio)
            p.drawPixmap(QPointF(pic.center().x() - 14, pic.center().y() - 14), mark)
            p.setFont(data_font())
            p.setPen(QColor(c["text_muted"]))
            p.drawText(pic.adjusted(10, 0, -10, -8), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       p.fontMetrics().elidedText(path.name, Qt.TextElideMode.ElideMiddle, int(pic.width()) - 20))
            drawn = True
        if not drawn:
            self._paint_blank(p, pic, job, c)

        state, token, percent = cell_state(job)
        if percent is not None:  # only a percent earns a bar
            p.fillRect(QRectF(pic.left(), pic.bottom(), pic.width() * min(1.0, percent / 100), 2),
                       QColor(c["live"]))
        if density == 1:
            band = QRectF(rect.left() + PAD, rect.top() + 4, pic.width() - 14, INDEX_BAND)
            p.setFont(data_font())
            p.setPen(QColor(c["faint"]))
            number = str(job.index)
            p.drawText(band, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, number)
            ident = ident_text(job)
            if ident:
                x = p.fontMetrics().horizontalAdvance(number) + 6
                p.setFont(ui_font())
                p.setPen(QColor(c["text_muted"]))
                p.drawText(band.adjusted(x, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(ident, Qt.TextElideMode.ElideRight, max(0, int(band.width() - x))))
        if density == 2:
            self._paint_top_row(p, QRectF(rect.left() + PAD, rect.top() + PAD, pic.width() - 14, TOP_ROW), job, c)
        if density >= 1:
            row = QRectF(pic.left(), pic.bottom() + 2, pic.width(), BOTTOM_ROW - 2)
            self._paint_bottom_row(p, row, job, state, token, c, selected or hovered)

        dot = "live" if is_live(job) else "failed" if job.status is JobStatus.FAILED else ""
        if dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c[dot]))
            p.drawEllipse(QRectF(rect.right() - PAD - 6, rect.top() + PAD - 4, 7, 7))
        stage = self.view.group_start(index.row())
        if stage:
            self._paint_stage_mark(p, pic, stage, c)
        if is_live(job):
            p.setPen(QPen(QColor(c["live"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))
        elif selected:
            pen = QPen(QColor(c["text"]), 1)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))
        if self.view.dim_alpha and not selected:  # lights dim or out: only the chosen take stays lit
            p.fillRect(rect, QColor(0, 0, 0, round(255 * self.view.dim_alpha)))
        p.restore()

    def _paint_top_row(self, p: QPainter, row: QRectF, job: Job, c: dict) -> None:
        font = QFont(p.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.Light)
        p.setFont(font)
        p.setPen(QColor(c["faint"]))
        number = str(job.index)
        p.drawText(row, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, number)
        x = p.fontMetrics().horizontalAdvance(number) + 8
        ident = ident_text(job)
        if ident:
            p.setFont(data_font())
            p.setPen(QColor(c["text_muted"]))
            p.drawText(row.adjusted(x, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(ident, Qt.TextElideMode.ElideRight, max(0, int(row.width() - x))))

    def _paint_bottom_row(self, p: QPainter, row: QRectF, job: Job, state: str, token: str, c: dict,
                          active: bool) -> None:
        x = row.left()
        mid = row.center().y()
        if job.review == "approved":
            draw_flag(p, QRectF(x, mid - 5, 10, 10), c["accent"])
            x += 14
        elif job.review == "rejected":
            p.drawPixmap(QPointF(x, mid - 5), icons.pixmap("x", c["accent"], 10, self.view.devicePixelRatioF()))
            x += 14
        if job.rating > 0 or active:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(5):
                p.setBrush(QColor(c["star" if i < job.rating else "star_empty"]))
                p.drawPolygon(star_polygon(QPointF(x + 4.5, mid), 4.5))
                x += 11
            x += 3
        if job.label in LABELS:
            p.fillRect(QRectF(x, mid - 4, 8, 8), QColor(c[f"label_{job.label}"]))
            x += 12
        p.setFont(ui_font())
        p.setPen(QColor(c[token]))
        room = max(0, int(row.right() - x - 4))
        p.drawText(row, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   p.fontMetrics().elidedText(state, Qt.TextElideMode.ElideRight, room))

    def _paint_stage_mark(self, p: QPainter, pic: QRectF, stage: str, c: dict) -> None:
        """The first frame of each Production stage carries the stage's name."""
        p.setFont(data_font())
        text = tr(f"gen_stage_{stage}")
        fm = p.fontMetrics()
        chip = QRectF(pic.left(), pic.top(), fm.horizontalAdvance(text) + 12, fm.height() + 4)
        p.fillRect(chip, QColor(c["header"]))
        p.setPen(QColor(c["text"]))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_blank(self, p: QPainter, pic: QRectF, job: Job, c: dict) -> None:
        """A frame with no picture yet shows its prompt, or why it failed."""
        failed = job.status is JobStatus.FAILED
        if failed:
            draw_hatch(p, pic, c["failed"])
        font = QFont(p.font())
        font.setPixelSize(11 if failed else 12)
        p.setFont(font)
        running = job.status is JobStatus.RUNNING
        p.setPen(QColor(c["failed"] if failed else c["text"] if running else c["text_muted"]))
        text = (job.error or job.prompt) if failed else job.prompt
        area = pic.adjusted(10, 9, -10, -6)
        lines = max(1, int(area.height() // p.fontMetrics().lineSpacing()))
        p.drawText(area, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   _clip(p, text, int(area.width()), lines))


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
    "stale": lambda job: bool(job.stale),
    "rated": lambda job: job.rating >= 1,
    "labelled": lambda job: bool(job.label),
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
    marks_changed = Signal(list)      # rows whose rating or label changed
    density_changed = Signal(int)

    def __init__(self, model, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sheet")
        self._width = 240
        self._filter = "all"
        self.filtered_rows = range(0)
        self._hidden = 0  # rows the filter hides, kept as rows change so a count never loops them all
        self.density = 1  # 0 picture, 1 compact, 2 expanded
        self.dim_alpha = 0.0  # the lights: black over every cell but the selected ones
        self._stage_starts: dict[int, str] | None = None  # None: worked out again on the next paint
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
        for sig in (model.rowsRemoved, model.modelReset):
            sig.connect(lambda *_: self.apply_filter())
        model.rowsInserted.connect(lambda _parent, first, last: self.apply_filter(first, last))
        model.dataChanged.connect(lambda tl, br, *_: self.apply_filter(tl.row(), br.row()))
        thumbs().ready.connect(self._thumb_ready)

    # ---- layout ------------------------------------------------------
    def _cell_width(self) -> int:
        """``_width`` is the slider's minimum: whole columns fill the viewport, the slack shared out."""
        gap = self.spacing()
        room = self.viewport().width() - gap - 1  # Qt wraps a cell that would touch the edge
        cols = max(1, room // (self._width + gap))
        return max(self._width, room // cols - gap)

    def _bands(self) -> tuple[int, int]:
        """Heights above and below the picture, inside the padding, for the current density."""
        top = {0: 0, 1: INDEX_BAND, 2: TOP_ROW}[self.density]
        return top, BOTTOM_ROW if self.density else 0

    def frame_size(self) -> QSize:
        w = self._cell_width()
        top, bottom = self._bands()
        return QSize(w, round((w - 2 * PAD) * FRAME_RATIO) + 2 * PAD + top + bottom)

    def picture_rect(self, cell: QRectF) -> QRectF:
        top, bottom = self._bands()
        return cell.adjusted(PAD, PAD + top, -PAD, -PAD - bottom)

    def cycle_density(self) -> int:
        self.density = DENSITIES[(DENSITIES.index(self.density) + 1) % len(DENSITIES)]
        self._relayout()
        self.density_changed.emit(self.density)
        return self.density

    def set_dim(self, alpha: float) -> None:
        self.dim_alpha = alpha
        self.viewport().update()

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
        return self.model().rowCount() - self._hidden

    def apply_filter(self, first: int = 0, last: int | None = None) -> None:
        """All rows, or only ``first``..``last`` when a model signal says just those changed."""
        test = FILTERS[self._filter]
        whole = last is None
        if whole:
            last = self.model().rowCount() - 1
            self._hidden = 0
        for row in range(first, last + 1):
            hide = not test(self.model().job_at(row))
            was = self.isRowHidden(row)
            if was != hide:
                self.setRowHidden(row, hide)
            if whole:
                self._hidden += hide
            elif was != hide:
                self._hidden += 1 if hide else -1
        self.filtered_rows = range(first, last + 1)  # what this pass looked at, for the queue to mirror
        self._stage_starts = None
        self.filter_changed.emit(self.visible_count())

    def setRowHidden(self, row: int, hide: bool) -> None:  # noqa: N802 - Qt override
        super().setRowHidden(row, hide)
        self._stage_starts = None

    def _index_stages(self) -> None:
        """Which shown row starts each Production stage, worked out once per change, not per painted cell."""
        model = self.model()
        starts: dict[int, str] = {}
        seen: set[str] = set()
        for r in range(model.rowCount()):
            stage = model.job_at(r).production_stage
            if stage and stage not in seen and not self.isRowHidden(r):
                seen.add(stage)
                starts[r] = stage
        self._stage_starts = starts if len(seen) >= 2 else {}

    def group_start(self, row: int) -> str:
        """The stage name when ``row`` is the first shown frame of its Production stage, else ""."""
        if self._stage_starts is None:
            self._index_stages()
        return self._stage_starts.get(row, "")

    def _thumb_ready(self, path: str) -> None:
        """Repaint only the frames showing ``path``."""
        for row in self.model().rows_showing(path):
            if not self.isRowHidden(row):
                self.viewport().update(self.visualRect(self.model().index(row, COL_OUTPUT)))

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
        if key == Qt.Key.Key_J and not ctrl:
            self.cycle_density()
            return
        if rows and not ctrl and (Qt.Key.Key_0 <= key <= Qt.Key.Key_9):
            self.mark_rows(rows, key)
            return
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

    def mark_rows(self, rows: list[int], key: int) -> None:
        """0-5 set the rating (0 clears); 6-9 toggle a colour label. Local only, never a credit."""
        label = LABEL_KEYS.get(Qt.Key(key))
        if label is not None:
            self.label_rows(rows, label)
            return
        for row in rows:
            self.model().job_at(row).rating = key - Qt.Key.Key_0
        self.marks_changed.emit(rows)

    def label_rows(self, rows: list[int], label: str) -> None:
        """Toggle a colour label: the same label again clears it."""
        for row in rows:
            job = self.model().job_at(row)
            job.label = "" if job.label == label else label
        self.marks_changed.emit(rows)

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
        for sig in (model.rowsInserted, model.rowsRemoved, model.modelReset):
            sig.connect(lambda *_: self.update())
        model.dataChanged.connect(self._rows_changed)

    def _rows_changed(self, tl, br, *_) -> None:
        """Repaint only the ticks of the changed rows."""
        n = len(self.model_.jobs)
        if n and self.width():
            tick = self.width() / n
            x0, x1 = int(tl.row() * tick), math.ceil((br.row() + 1) * tick)
            self.update(QRect(x0, 0, max(1, x1 - x0), self.height()))

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
        area = event.rect()
        first = max(0, int(area.left() / tick) - 1)
        last = min(len(jobs), int((area.right() + 1) / tick) + 2)
        for i in range(first, last):
            job = jobs[i]
            p.fillRect(QRectF(i * tick, 0, max(1.0, tick - gap), self.height()), self._color(job, c))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        jobs = self.model_.jobs
        if jobs and self.width():
            self.row_clicked.emit(min(len(jobs) - 1, int(event.position().x() / self.width() * len(jobs))))
