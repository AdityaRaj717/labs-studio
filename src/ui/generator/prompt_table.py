"""PromptTable: the view over PromptTableModel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
)

from src import theme
from src.gen.models import JobStatus
from src.i18n import tr
from src.ui.generator.prompt_model import (
    COL_CHARACTER, COL_INDEX, COL_OUTPUT, COL_PROGRESS, COL_PROMPT, COL_REFS, COL_SCENE, COL_STATUS,
    THUMB_HEIGHT, status_color,
)
from src.ui.kit import data_font

IMPORT_SUFFIXES = {".txt", ".text", ".csv", ".xlsx", ".xlsm"}
NARROW_TABLE = 760  # below this the prompt keeps the room; cast, scene and refs stay in the Take panel


class ProgressDelegate(QStyledItemDelegate):
    """Draws the bar itself from theme tokens, so it reads the same in both modes
    and on every platform style (the Windows 11 style drew a faint line and lost
    the text colour in light mode)."""

    BAR_HEIGHT = 4

    def paint(self, painter: QPainter, option, index) -> None:
        value = index.data()
        if value is None or isinstance(value, str):  # "0:42 elapsed": no percent, so no bar
            return super().paint(painter, option, index)
        cell = QStyleOptionViewItem(option)  # the row's selection and rule, without the number
        self.initStyleOption(cell, index)
        cell.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, option.widget)
        colors = theme.COLORS[theme.current_mode()]
        job = index.model().job_at(index.row())
        done_or_failed = job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.STOPPED)
        fill = QColor(status_color(job) if done_or_failed else colors["live"])

        rect = option.rect.adjusted(8, 0, -8, 0)
        text_w = 32
        track = QRectF(rect.left(), rect.center().y() - self.BAR_HEIGHT / 2 + 1,
                       max(10, rect.width() - text_w - 6), self.BAR_HEIGHT)

        painter.save()
        painter.fillRect(track, QColor(colors["border"]))
        frac = max(0.0, min(1.0, int(value) / 100))
        if frac > 0:
            filled = QRectF(track)
            filled.setWidth(track.width() * frac)
            painter.fillRect(filled, fill)
        painter.setPen(QColor(colors["text"]))
        painter.setFont(data_font())
        text_rect = QRectF(track.right() + 6, rect.top(), text_w, rect.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                         f"{int(value)}%")
        painter.restore()


class StatusDelegate(QStyledItemDelegate):
    """Qt draws selected text in HighlightedText and drops the model's foreground, so a selected
    failed row would lose its colour: hand the foreground over."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 - Qt override
        super().initStyleOption(option, index)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if fg is not None:
            option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor(fg))


class PromptTable(QTableView):
    files_dropped = Signal(list)          # list[Path]
    edit_requested = Signal(int)          # row
    retry_requested = Signal(list)        # rows
    cancel_requested = Signal(list)       # rows: queued frames leave the run
    remove_requested = Signal(list)       # rows
    open_output_requested = Signal(int)   # row
    open_folder_requested = Signal(int)   # row
    character_requested = Signal(list, str)  # rows, character id ("" = detach)
    character_added = Signal(list, str)      # rows, character id joining the shot (Phase 14b)
    scene_requested = Signal(list, str)      # rows, scene id ("" = clear) (Phase 14b)
    approve_requested = Signal(list)         # rows
    reject_requested = Signal(list)          # rows
    regenerate_requested = Signal(list)      # rows
    animate_requested = Signal(list)         # rows: stills to animate on the video page
    chain_requested = Signal(int)            # row: its video's last frame starts the next shot

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self))
        status = StatusDelegate(self)
        self.setItemDelegateForColumn(COL_STATUS, status)
        self.setItemDelegateForColumn(COL_OUTPUT, status)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.SelectedClicked)
        self.setWordWrap(True)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(THUMB_HEIGHT + 8)
        self.setIconSize(QSize(THUMB_HEIGHT * 2, THUMB_HEIGHT))
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(COL_PROMPT, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_INDEX, 40), (COL_CHARACTER, 96), (COL_SCENE, 84), (COL_REFS, 40),
                           (COL_STATUS, 88), (COL_PROGRESS, 96), (COL_OUTPUT, THUMB_HEIGHT * 3 // 2 + 16)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(col, width)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.doubleClicked.connect(self._double_clicked)
        self.characters_source = None  # callable -> list[(id, name)], set by GeneratorPage
        self.scenes_source = None  # callable -> list[(id, name)], set by GeneratorPage (Phase 14b)
        self.animate_enabled = False  # the image page: a still can go on to the video page
        self.chain_enabled = False  # the video page: a clip's last frame starts the next shot

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        narrow = event.size().width() < NARROW_TABLE
        for col in (COL_CHARACTER, COL_SCENE, COL_REFS):
            self.setColumnHidden(col, narrow)

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
        self._build_menu(index.row(), self.selected_rows()).exec(self.viewport().mapToGlobal(pos))

    def _build_menu(self, row: int, rows: list[int]) -> QMenu:
        job = self.model().job_at(row)
        menu = QMenu(self)
        if job.production_id:
            self._production_menu(menu, row, rows)
        else:
            done = any(self.model().job_at(r).status is JobStatus.DONE for r in rows)
            menu.addAction(tr("gen_approve"), lambda: self.approve_requested.emit(rows)).setEnabled(done)
            menu.addAction(tr("gen_reject"), lambda: self.reject_requested.emit(rows)).setEnabled(done)
            menu.addSeparator()
            menu.addAction(tr("gen_edit"), lambda: self.edit_requested.emit(row))
            menu.addAction(tr("gen_retry"), lambda: self.retry_requested.emit(rows))
            queued = any(self.model().job_at(r).status is JobStatus.QUEUED for r in rows)
            menu.addAction(tr("gen_cancel_frame"), lambda: self.cancel_requested.emit(rows)).setEnabled(queued)
            menu.addAction(tr("gen_remove"), lambda: self.remove_requested.emit(rows))
            if self.characters_source is not None:
                self._character_menu(menu, rows, job)
            if self.scenes_source is not None:
                self._scene_menu(menu, rows, job)
        self._frames_menu(menu, row, rows)
        menu.addSeparator()
        out = menu.addAction(tr("gen_open_output"), lambda: self.open_output_requested.emit(row))
        folder = menu.addAction(tr("gen_open_folder"), lambda: self.open_folder_requested.emit(row))
        out.setEnabled(bool(job.outputs))
        folder.setEnabled(bool(job.outputs))
        return menu

    def _frames_menu(self, menu: QMenu, row: int, rows: list[int]) -> None:
        """Stills go on to the video page; a finished clip hands its last frame to the next shot."""
        from src.ui.generator.sheet import is_video
        job = self.model().job_at(row)
        if self.animate_enabled:
            stills = [r for r in rows if (j := self.model().job_at(r)).outputs and not is_video(j.outputs[0])]
            menu.addSeparator()
            menu.addAction(tr("gen_animate_still"), lambda: self.animate_requested.emit(stills)).setEnabled(bool(stills))
        if self.chain_enabled:
            clip = bool(job.outputs) and is_video(job.outputs[0]) and len(rows) == 1
            menu.addSeparator()
            menu.addAction(tr("gen_chain_last_frame"), lambda: self.chain_requested.emit(row)).setEnabled(clip)

    def _pending(self, rows: list[int]) -> bool:
        return any(self.model().job_at(r).review == "pending_review" for r in rows)

    def _production_menu(self, menu: QMenu, row: int, rows: list[int]) -> None:
        approve = menu.addAction(tr("gen_approve"), lambda: self.approve_requested.emit(rows))
        approve.setShortcut(QKeySequence("Ctrl+Return"))
        approve.setEnabled(self._pending(rows))
        reject = menu.addAction(tr("gen_reject"), lambda: self.reject_requested.emit(rows))
        reject.setEnabled(any(self.model().job_at(r).review in ("pending_review", "approved") for r in rows))
        menu.addAction(tr("gen_retry_same"), lambda: self.regenerate_requested.emit(rows))
        modify = menu.addAction(tr("gen_modify_regen"), lambda: self.edit_requested.emit(row))
        modify.setEnabled(len(rows) == 1)
        menu.addAction(tr("gen_remove")).setEnabled(False)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            rows = self.selected_rows()
            if self._pending(rows):
                self.approve_requested.emit(rows)
                return
        super().keyPressEvent(event)

    def _character_menu(self, menu: QMenu, rows: list[int], job) -> None:
        sub = menu.addMenu(tr("gen_attach_character"))
        chars = self.characters_source()
        for char_id, name in chars:
            act = sub.addAction(name, lambda cid=char_id: self.character_requested.emit(rows, cid))
            act.setCheckable(True)
            act.setChecked(job.character == char_id)
        if not chars:
            sub.addAction(tr("gen_no_characters")).setEnabled(False)
        if chars:
            add = menu.addMenu(tr("gen_add_character"))
            for char_id, name in chars:
                act = add.addAction(name, lambda cid=char_id: self.character_added.emit(rows, cid))
                act.setEnabled(job.character != char_id and char_id not in job.cast)
        detach = menu.addAction(tr("gen_detach_character"), lambda: self.character_requested.emit(rows, ""))
        detach.setEnabled(any(self.model().job_at(r).character for r in rows))

    def _scene_menu(self, menu: QMenu, rows: list[int], job) -> None:
        sub = menu.addMenu(tr("gen_set_scene"))
        scenes = self.scenes_source()
        for scene_id, name in scenes:
            act = sub.addAction(name, lambda sid=scene_id: self.scene_requested.emit(rows, sid))
            act.setCheckable(True)
            act.setChecked(scene_id in job.scenes)
        if not scenes:
            sub.addAction(tr("gen_no_scenes")).setEnabled(False)
        clear = menu.addAction(tr("gen_clear_scene"), lambda: self.scene_requested.emit(rows, ""))
        clear.setEnabled(any(self.model().job_at(r).scenes for r in rows))

    def _double_clicked(self, index) -> None:
        if index.column() == COL_OUTPUT:
            self.open_output_requested.emit(index.row())
        elif index.column() in (COL_INDEX, COL_CHARACTER, COL_SCENE, COL_REFS, COL_STATUS, COL_PROGRESS):
            self.edit_requested.emit(index.row())
        else:
            self.edit(index)
