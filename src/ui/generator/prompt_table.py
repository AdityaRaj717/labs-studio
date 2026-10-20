"""PromptTable: the view over PromptTableModel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QStyledItemDelegate, QTableView,
)

from src import theme
from src.gen.models import JobStatus
from src.i18n import tr
from src.ui.generator.prompt_model import (
    COL_INDEX, COL_OUTPUT, COL_PROGRESS, COL_PROMPT, COL_REFS, COL_STATUS, STATUS_COLORS, THUMB_HEIGHT,
)

IMPORT_SUFFIXES = {".txt", ".text", ".csv", ".xlsx", ".xlsm"}


class ProgressDelegate(QStyledItemDelegate):
    """Draws the bar itself from theme tokens, so it reads the same in both modes
    and on every platform style (the Windows 11 style drew a faint line and lost
    the text colour in light mode)."""

    BAR_HEIGHT = 14

    def paint(self, painter: QPainter, option, index) -> None:
        value = index.data()
        if value is None:
            return super().paint(painter, option, index)
        colors = theme.COLORS[theme.current_mode()]
        status = index.model().job_at(index.row()).status
        done_or_failed = status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.STOPPED)
        fill = QColor(STATUS_COLORS[status] if done_or_failed else colors["accent"])

        rect = option.rect.adjusted(8, 0, -8, 0)
        text_w = 40
        track = QRectF(rect.left(), rect.center().y() - self.BAR_HEIGHT / 2 + 1,
                       max(10, rect.width() - text_w - 6), self.BAR_HEIGHT)
        radius = self.BAR_HEIGHT / 2

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["border"]))
        painter.drawRoundedRect(track, radius, radius)
        frac = max(0.0, min(1.0, int(value) / 100))
        if frac > 0:
            filled = QRectF(track)
            filled.setWidth(max(track.height(), track.width() * frac))
            painter.setBrush(fill)
            painter.drawRoundedRect(filled, radius, radius)
        painter.setPen(QColor(colors["text"]))
        text_rect = QRectF(track.right() + 6, rect.top(), text_w, rect.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                         f"{int(value)}%")
        painter.restore()


class PromptTable(QTableView):
    files_dropped = Signal(list)          # list[Path]
    edit_requested = Signal(int)          # row
    retry_requested = Signal(list)        # rows
    remove_requested = Signal(list)       # rows
    open_output_requested = Signal(int)   # row
    open_folder_requested = Signal(int)   # row
    character_requested = Signal(list, str)  # rows, character id ("" = detach)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.SelectedClicked)
        self.setWordWrap(True)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(THUMB_HEIGHT + 8)
        self.setIconSize(QSize(THUMB_HEIGHT * 2, THUMB_HEIGHT))
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_PROMPT, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_INDEX, 44), (COL_REFS, 90), (COL_STATUS, 100),
                           (COL_PROGRESS, 120), (COL_OUTPUT, 150)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(col, width)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.doubleClicked.connect(self._double_clicked)
        self.characters_source = None  # callable -> list[(id, name)], set by GeneratorPage

    # ---- empty state -------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.model().rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(theme.COLORS[theme.current_mode()]["text_muted"]))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, tr("gen_empty_hint"))
            painter.end()

    # ---- drag and drop -----------------------------------------------
    @staticmethod
    def _import_paths(event) -> list[Path]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
        return [p for p in paths if p.suffix.lower() in IMPORT_SUFFIXES]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._import_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._import_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._import_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    # ---- actions -----------------------------------------------------
    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedRows()})

    def _context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        if index.row() not in self.selected_rows():
            self.selectRow(index.row())
        rows = self.selected_rows()
        job = self.model().job_at(index.row())
        menu = QMenu(self)
        menu.addAction(tr("gen_edit"), lambda: self.edit_requested.emit(index.row()))
        menu.addAction(tr("gen_retry"), lambda: self.retry_requested.emit(rows))
        menu.addAction(tr("gen_remove"), lambda: self.remove_requested.emit(rows))
        if self.characters_source is not None:
            self._character_menu(menu, rows, job)
        menu.addSeparator()
        out = menu.addAction(tr("gen_open_output"), lambda: self.open_output_requested.emit(index.row()))
        folder = menu.addAction(tr("gen_open_folder"), lambda: self.open_folder_requested.emit(index.row()))
        out.setEnabled(bool(job.outputs))
        folder.setEnabled(bool(job.outputs))
        menu.exec(self.viewport().mapToGlobal(pos))

    def _character_menu(self, menu: QMenu, rows: list[int], job) -> None:
        sub = menu.addMenu(tr("gen_attach_character"))
        chars = self.characters_source()
        for char_id, name in chars:
            act = sub.addAction(name, lambda cid=char_id: self.character_requested.emit(rows, cid))
            act.setCheckable(True)
            act.setChecked(job.character == char_id)
        if not chars:
            sub.addAction(tr("gen_no_characters")).setEnabled(False)
        detach = menu.addAction(tr("gen_detach_character"), lambda: self.character_requested.emit(rows, ""))
        detach.setEnabled(any(self.model().job_at(r).character for r in rows))

    def _double_clicked(self, index) -> None:
        if index.column() == COL_OUTPUT:
            self.open_output_requested.emit(index.row())
        elif index.column() in (COL_INDEX, COL_REFS, COL_STATUS, COL_PROGRESS):
            self.edit_requested.emit(index.row())
        else:
            self.edit(index)
