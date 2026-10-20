"""Side panels of the editor: clip inspector, project settings, subtitles + style."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.editor.model import Clip, Cue, Project
from src.editor.subtitles import format_srt_time, parse_srt_time
from src.i18n import tr

RESOLUTIONS = [
    ("1920 × 1080 (16:9)", 1920, 1080), ("1280 × 720 (16:9)", 1280, 720),
    ("1080 × 1920 (9:16)", 1080, 1920), ("1080 × 1080 (1:1)", 1080, 1080),
    ("3840 × 2160 (4K)", 3840, 2160),
]


def _spin(lo: float, hi: float, step: float = 0.1, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str = "#ffffff", parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setStyleSheet(f"background-color: {color}; border: 1px solid #777; min-height: 18px;")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self)
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(self.color)


class ClipInspector(QWidget):
    """Edits the selected clip. Emits ``aboutToEdit`` before and ``edited`` after a change."""

    aboutToEdit = Signal()
    edited = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.clip: Clip | None = None
        self.track = None
        self._loading = False
        lay = QVBoxLayout(self)
        self.title = QLabel(tr("ed_no_selection"))
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        form = QFormLayout()
        lay.addLayout(form)
        lay.addStretch(1)
        self.start = _spin(0, 36000, suffix=" s")
        self.duration = _spin(0.1, 36000, suffix=" s")
        self.in_point = _spin(0, 36000, suffix=" s")
        self.fade_in = _spin(0, 60, suffix=" s")
        self.fade_out = _spin(0, 60, suffix=" s")
        self.volume = _spin(0, 4, 0.05)
        self.track_volume = _spin(0, 4, 0.05)
        self.loop = QCheckBox(tr("ed_loop"))
        self.x = _spin(0, 1, 0.05)
        self.y = _spin(0, 1, 0.05)
        self.scale = _spin(0.02, 1, 0.05)
        self.opacity = _spin(0, 1, 0.05)
        self.text = QPlainTextEdit()
        self.text.setFixedHeight(64)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 400)
        self.color = ColorButton()
        self.rows: dict[str, QWidget] = {}
        for key, w in [("start", self.start), ("duration", self.duration), ("in_point", self.in_point),
                       ("fade_in", self.fade_in), ("fade_out", self.fade_out), ("volume", self.volume),
                       ("track_volume", self.track_volume), ("loop", self.loop), ("x", self.x), ("y", self.y),
                       ("scale", self.scale), ("opacity", self.opacity), ("text", self.text),
                       ("font_size", self.font_size), ("color", self.color)]:
            form.addRow(tr(f"ed_f_{key}"), w)
            self.rows[key] = w
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self._apply)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._apply)
        self.text.textChanged.connect(self._apply)
        self.color.changed.connect(self._apply)
        self._form = form
        self.set_clip(None, None)

    def set_clip(self, clip: Clip | None, track) -> None:
        self.clip, self.track = clip, track
        self._loading = True
        try:
            for key, w in self.rows.items():
                self._form.setRowVisible(w, False)
            if clip is None:
                self.title.setText(tr("ed_no_selection"))
                return
            self.title.setText(f"<b>{clip.name}</b><br>{tr('ed_kind_' + clip.kind)} · {track.name if track else ''}")
            visible = ["start", "duration", "fade_in", "fade_out", "opacity"]
            if clip.kind in ("video", "audio"):
                visible += ["in_point", "volume", "track_volume", "loop"]
            if clip.kind == "audio":
                visible.remove("opacity")
            if clip.kind == "text":
                visible += ["text", "font_size", "color", "x", "y"]
            elif track is not None and track.kind == "overlay":
                visible += ["x", "y", "scale"]
            for key in visible:
                self._form.setRowVisible(self.rows[key], True)
            for key in ("start", "duration", "in_point", "fade_in", "fade_out", "volume", "x", "y",
                        "scale", "opacity"):
                self.rows[key].setValue(getattr(clip, key))
            self.track_volume.setValue(track.volume if track else 1.0)
            self.loop.setChecked(clip.loop)
            self.text.setPlainText(clip.text)
            self.font_size.setValue(clip.font_size)
            self.color.set_color(clip.color)
        finally:
            self._loading = False

    def _apply(self, *_):
        if self._loading or self.clip is None:
            return
        self.aboutToEdit.emit()
        c = self.clip
        c.start = self.start.value()
        c.duration = self.duration.value()
        c.in_point = self.in_point.value()
        c.loop = self.loop.isChecked()
        limit = c.max_duration()
        if limit is not None and c.duration > limit:
            c.duration = round(limit, 3)
        c.fade_in = min(self.fade_in.value(), c.duration)
        c.fade_out = min(self.fade_out.value(), c.duration)
        c.volume = self.volume.value()
        c.x, c.y = self.x.value(), self.y.value()
        c.scale, c.opacity = self.scale.value(), self.opacity.value()
        if c.kind == "text":
            c.text = self.text.toPlainText()
        c.font_size = self.font_size.value()
        c.color = self.color.color
        if self.track is not None:
            self.track.volume = self.track_volume.value()
        self.edited.emit()


class ProjectPanel(QWidget):
    aboutToEdit = Signal()
    edited = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.project: Project | None = None
        self._loading = False
        form = QFormLayout(self)
        self.resolution = QComboBox()
        for label, w, h in RESOLUTIONS:
            self.resolution.addItem(label, (w, h))
        self.fps = QComboBox()
        for f in (24, 25, 30, 50, 60):
            self.fps.addItem(str(f), f)
        self.background = ColorButton("#000000")
        form.addRow(tr("ed_resolution"), self.resolution)
        form.addRow(tr("ed_fps"), self.fps)
        form.addRow(tr("ed_background"), self.background)
        self.resolution.currentIndexChanged.connect(self._apply)
        self.fps.currentIndexChanged.connect(self._apply)
        self.background.changed.connect(self._apply)

    def set_project(self, project: Project) -> None:
        self.project = project
        self._loading = True
        try:
            i = self.resolution.findData((project.width, project.height))
            if i < 0:
                self.resolution.addItem(f"{project.width} × {project.height}", (project.width, project.height))
                i = self.resolution.count() - 1
            self.resolution.setCurrentIndex(i)
            j = self.fps.findData(project.fps)
            if j < 0:
                self.fps.addItem(str(project.fps), project.fps)
                j = self.fps.count() - 1
            self.fps.setCurrentIndex(j)
            self.background.set_color(project.background)
        finally:
            self._loading = False

    def _apply(self, *_):
        if self._loading or self.project is None:
            return
        self.aboutToEdit.emit()
        self.project.width, self.project.height = self.resolution.currentData()
        self.project.fps = self.fps.currentData()
        self.project.background = self.background.color
        self.edited.emit()


class SubtitlePanel(QWidget):
    """Cue table (start / end / text, editable) and the style form."""

    aboutToEdit = Signal()
    edited = Signal()
    importRequested = Signal()
    exportRequested = Signal()
    seekRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.project: Project | None = None
        self.playhead = 0.0
        self._loading = False
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_add = QPushButton(tr("ed_sub_add"))
        self.btn_del = QPushButton(tr("ed_sub_remove"))
        self.btn_import = QPushButton(tr("ed_sub_import"))
        self.btn_export = QPushButton(tr("ed_sub_export"))
        for b in (self.btn_add, self.btn_del, self.btn_import, self.btn_export):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("ed_sub_start"), tr("ed_sub_end"), tr("ed_sub_text")])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)

        self.burn = QCheckBox(tr("ed_sub_burn"))
        lay.addWidget(self.burn)
        form = QFormLayout()
        lay.addLayout(form)
        self.font = QFontComboBox()
        self.size = QSpinBox()
        self.size.setRange(8, 300)
        self.color = ColorButton()
        self.outline_color = ColorButton("#000000")
        self.outline = _spin(0, 20, 0.5, 1)
        self.shadow = _spin(0, 20, 0.5, 1)
        self.bold = QCheckBox(tr("ed_bold"))
        self.italic = QCheckBox(tr("ed_italic"))
        style_row = QHBoxLayout()
        style_row.addWidget(self.bold)
        style_row.addWidget(self.italic)
        style_row.addStretch(1)
        self.position = QComboBox()
        for pos in ("bottom", "middle", "top"):
            self.position.addItem(tr(f"ed_pos_{pos}"), pos)
        self.margin = QSpinBox()
        self.margin.setRange(0, 1000)
        self.box = QCheckBox(tr("ed_box"))
        self.box_color = ColorButton("#000000")
        self.box_opacity = _spin(0, 1, 0.05)
        form.addRow(tr("ed_font"), self.font)
        form.addRow(tr("ed_size"), self.size)
        form.addRow(tr("ed_text_color"), self.color)
        form.addRow(tr("ed_outline"), self._pair(self.outline, self.outline_color))
        form.addRow(tr("ed_shadow"), self.shadow)
        form.addRow("", style_row)
        form.addRow(tr("ed_position"), self.position)
        form.addRow(tr("ed_margin"), self.margin)
        form.addRow(self.box, self._pair(self.box_color, self.box_opacity))

        self.btn_add.clicked.connect(self.add_cue)
        self.btn_del.clicked.connect(self.remove_selected)
        self.btn_import.clicked.connect(self.importRequested)
        self.btn_export.clicked.connect(self.exportRequested)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.cellDoubleClicked.connect(self._seek_row)
        for w in (self.size, self.margin):
            w.valueChanged.connect(self._style_changed)
        for w in (self.outline, self.shadow, self.box_opacity):
            w.valueChanged.connect(self._style_changed)
        for w in (self.bold, self.italic, self.box, self.burn):
            w.toggled.connect(self._style_changed)
        for w in (self.color, self.outline_color, self.box_color):
            w.changed.connect(self._style_changed)
        self.font.currentFontChanged.connect(self._style_changed)
        self.position.currentIndexChanged.connect(self._style_changed)

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a)
        h.addWidget(b)
        h.addStretch(1)
        return w

    def set_project(self, project: Project) -> None:
        self.project = project
        self._loading = True
        try:
            s = project.style
            self.font.setCurrentFont(QFont(s.font))
            self.size.setValue(s.size)
            self.color.set_color(s.color)
            self.outline_color.set_color(s.outline_color)
            self.outline.setValue(s.outline)
            self.shadow.setValue(s.shadow)
            self.bold.setChecked(s.bold)
            self.italic.setChecked(s.italic)
            self.position.setCurrentIndex(max(0, self.position.findData(s.position)))
            self.margin.setValue(s.margin_v)
            self.box.setChecked(s.box)
            self.box_color.set_color(s.box_color)
            self.box_opacity.setValue(s.box_opacity)
            self.burn.setChecked(project.burn_subtitles)
        finally:
            self._loading = False
        self.refresh()

    def refresh(self) -> None:
        if self.project is None:
            return
        self._loading = True
        try:
            self.table.setRowCount(len(self.project.cues))
            for row, cue in enumerate(self.project.cues):
                for col, val in enumerate((format_srt_time(cue.start), format_srt_time(cue.end), cue.text)):
                    item = QTableWidgetItem(val)
                    if col < 2:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, col, item)
            self.table.resizeColumnsToContents()
        finally:
            self._loading = False

    def select_cue(self, cue: Cue) -> None:
        if self.project and cue in self.project.cues:
            self.table.selectRow(self.project.cues.index(cue))

    def add_cue(self) -> None:
        if self.project is None:
            return
        self.aboutToEdit.emit()
        t = round(self.playhead, 3)
        self.project.cues.append(Cue(t, t + 2.0, tr("ed_sub_new_text")))
        self.project.sort_cues()
        self.refresh()
        self.edited.emit()

    def remove_selected(self) -> None:
        if self.project is None:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self.aboutToEdit.emit()
        for r in rows:
            if 0 <= r < len(self.project.cues):
                del self.project.cues[r]
        self.refresh()
        self.edited.emit()

    def _seek_row(self, row: int, col: int) -> None:
        if self.project and col < 2 and row < len(self.project.cues):
            self.seekRequested.emit(self.project.cues[row].start)

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.project is None or item.row() >= len(self.project.cues):
            return
        cue = self.project.cues[item.row()]
        self.aboutToEdit.emit()
        try:
            if item.column() == 0:
                cue.start = parse_srt_time(item.text().replace(".", ","))
            elif item.column() == 1:
                cue.end = parse_srt_time(item.text().replace(".", ","))
            else:
                cue.text = item.text().replace("\\n", "\n")
        except ValueError:
            pass
        if cue.end <= cue.start:
            cue.end = cue.start + 0.5
        self.project.sort_cues()
        self.refresh()
        self.edited.emit()

    def _style_changed(self, *_):
        if self._loading or self.project is None:
            return
        self.aboutToEdit.emit()
        s = self.project.style
        s.font = self.font.currentFont().family()
        s.size = self.size.value()
        s.color = self.color.color
        s.outline_color = self.outline_color.color
        s.outline = self.outline.value()
        s.shadow = self.shadow.value()
        s.bold = self.bold.isChecked()
        s.italic = self.italic.isChecked()
        s.position = self.position.currentData()
        s.margin_v = self.margin.value()
        s.box = self.box.isChecked()
        s.box_color = self.box_color.color
        s.box_opacity = self.box_opacity.value()
        self.project.burn_subtitles = self.burn.isChecked()
        self.edited.emit()
