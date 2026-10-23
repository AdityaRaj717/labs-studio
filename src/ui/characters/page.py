"""CharactersPage: list of saved characters on the left, the selected one's editor on the right.

Phase 14b: the same page with ``kind="scene"`` is the Scenes page (reusable places:
name, description, images, no voice). Both show where the entry is set up in
Google Flow and can set it up in the active project's Flow project.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from src import features
from src.characters.store import CharacterStore, default_store, scene_store
from src.characters.voices import VOICES, preview_voice, voice_label
from src.gen.refmatch import IMAGE_EXTS
from src.i18n import tr

log = logging.getLogger(__name__)

THUMB = 96
PREVIEW_TEXT = "Hello! This is how this voice sounds in Labs Studio."
ROLE_ID = Qt.ItemDataRole.UserRole


def _thumb(path: Path, size: int = THUMB) -> QIcon:
    pix = QPixmap(str(path))
    if pix.isNull():
        return QIcon()
    return QIcon(pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation))


class _PreviewSignals(QObject):
    done = Signal(str, str)  # (wav path, error)
    flow_done = Signal(str, str)  # (entry id, error) after a Flow setup


def _flow_setup(kind: str, entry_id: str) -> None:
    """Set the entry up in the active project's Flow project (worker thread)."""
    from src import projects
    from src.web.flow_mcp import flow_mcp

    project = projects.current()
    if project is None:
        raise RuntimeError(tr("char_flow_no_project"))
    mcp = flow_mcp()
    url = mcp.ensure_project(project)
    mcp.sync.ensure(kind, entry_id, url)


class RefList(QListWidget):
    """Thumbnail grid of a character's reference images; accepts dropped image files."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(6)
        self.setAcceptDrops(True)
        self.setMinimumHeight(THUMB + 50)

    @staticmethod
    def _paths(event) -> list[Path]:
        if not event.mimeData().hasUrls():
            return []
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        return [p for p in paths if p.suffix.lower() in IMAGE_EXTS]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        event.acceptProposedAction() if self._paths(event) else event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        event.acceptProposedAction() if self._paths(event) else event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class CharactersPage(QWidget):
    def __init__(self, store: CharacterStore | None = None, key_source=None, transport=None,
                 parent: QWidget | None = None, kind: str = "character", flow_setup=_flow_setup):
        super().__init__(parent)
        self.kind = kind
        self.store = store or (scene_store() if kind == "scene" else default_store())
        self._flow_setup = flow_setup
        prefix = "scene" if kind == "scene" else "char"
        self._k = lambda key: f"{prefix}_{key}"  # the kind's own string for "new", "empty"...
        flow_only = features.flow_only()
        self._key_source = key_source
        self._transport = transport
        self._current: str = ""
        self._player = None
        self._signals = _PreviewSignals(self)
        self._signals.done.connect(self._preview_done)
        self._signals.flow_done.connect(self._flow_done)

        heading = QLabel(tr("nav_scenes" if kind == "scene" else "nav_characters"))
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        intro = QLabel(tr("scene_intro" if kind == "scene" else "char_intro_flow" if flow_only else "char_intro"))
        intro.setWordWrap(True)
        intro.setObjectName("DemoBanner")

        # Left: list + new/delete.
        self.list = QListWidget()
        self.list.setIconSize(QSize(40, 40))
        self.list.setFixedWidth(260)
        self.list.currentItemChanged.connect(lambda cur, _prev: self._select(cur.data(ROLE_ID) if cur else ""))
        self.btn_new = QPushButton(tr(self._k("new")))
        self.btn_new.clicked.connect(lambda: self.new_character())
        self.btn_delete = QPushButton(tr("char_delete"))
        self.btn_delete.clicked.connect(lambda: self.delete_current())
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_delete)
        left.addLayout(row)

        # Right: editor.
        self.name_edit = QLineEdit()
        self.voice_combo = QComboBox()
        self.voice_combo.addItem(tr("char_voice_none"), "")
        for name, _style in VOICES:
            self.voice_combo.addItem(voice_label(name), name)
        self.btn_preview = QPushButton(tr("char_preview"))
        self.btn_preview.setToolTip(tr("char_preview_tip"))
        self.btn_preview.clicked.connect(lambda: self.preview())
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.btn_preview)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText(tr(
            "scene_notes_hint" if kind == "scene" else "char_notes_flow_hint" if flow_only else "char_notes_hint"))
        self.notes_edit.setMaximumHeight(110)
        self.refs = RefList()
        self.refs.files_dropped.connect(self.add_images)
        self.btn_add_refs = QPushButton(tr("char_add_refs"))
        self.btn_add_refs.clicked.connect(lambda: self.add_images_dialog())
        self.btn_remove_refs = QPushButton(tr("char_remove_refs"))
        self.btn_remove_refs.clicked.connect(lambda: self.remove_selected_refs())
        self.btn_save = QPushButton(tr("char_save"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(lambda: self.save_current())
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.flow_label = QLabel("")
        self.flow_label.setWordWrap(True)
        self.btn_flow = QPushButton(tr("char_flow_sync"))
        self.btn_flow.setToolTip(tr("char_flow_sync_tip"))
        self.btn_flow.clicked.connect(lambda: self.setup_in_flow())
        flow_row = QHBoxLayout()
        flow_row.addWidget(self.flow_label, 1)
        flow_row.addWidget(self.btn_flow)

        form = QFormLayout()
        form.addRow(tr("char_name"), self.name_edit)
        # Voices need a Gemini key (TTS); places have none.
        self.voice_row_shown = kind != "scene" and features.shown("characters:voice")
        if self.voice_row_shown:
            form.addRow(tr("char_voice"), voice_row)
        else:
            for w in (self.voice_combo, self.btn_preview):
                w.setVisible(False)
        form.addRow(tr("scene_notes" if kind == "scene" else "char_notes"), self.notes_edit)
        form.addRow(tr("char_flow"), flow_row)
        ref_buttons = QHBoxLayout()
        ref_buttons.addWidget(self.btn_add_refs)
        ref_buttons.addWidget(self.btn_remove_refs)
        ref_buttons.addStretch(1)
        ref_buttons.addWidget(self.btn_save)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(QLabel(tr("scene_refs" if kind == "scene" else "char_refs_flow" if flow_only else "char_refs")))
        right.addWidget(self.refs, 1)
        right.addLayout(ref_buttons)
        right.addWidget(self.status)
        self.editor = QWidget()
        self.editor.setLayout(right)
        self.empty = QLabel(tr(self._k("empty")))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QHBoxLayout()
        body.addLayout(left)
        body.addWidget(self.editor, 1)
        body.addWidget(self.empty, 1)
        outer = QVBoxLayout(self)
        outer.addWidget(heading)
        outer.addWidget(intro)
        outer.addLayout(body, 1)

        self.reload()

    # ---- list --------------------------------------------------------
    def reload(self, select: str = "") -> None:
        select = select or self._current
        self.list.blockSignals(True)
        self.list.clear()
        for char in self.store.all():
            item = QListWidgetItem(char.name)
            item.setData(ROLE_ID, char.id)
            refs = self.store.ref_paths(char.id)
            if refs:
                item.setIcon(_thumb(refs[0], 40))
            item.setToolTip(f"{char.name}\n{tr('char_ref_count', count=len(refs))}"
                            + (f"\n{voice_label(char.voice)}" if char.voice else ""))
            self.list.addItem(item)
        self.list.blockSignals(False)
        ids = [self.list.item(i).data(ROLE_ID) for i in range(self.list.count())]
        target = select if select in ids else (ids[0] if ids else "")
        if target:
            self.list.setCurrentRow(ids.index(target))
        self._select(target)

    def _select(self, char_id: str) -> None:
        self._current = char_id
        char = self.store.get(char_id) if char_id else None
        self.editor.setVisible(char is not None)
        self.empty.setVisible(char is None)
        self.btn_delete.setEnabled(char is not None)
        if not char:
            return
        self.name_edit.setText(char.name)
        idx = self.voice_combo.findData(char.voice)
        self.voice_combo.setCurrentIndex(max(idx, 0))
        self.notes_edit.setPlainText(char.notes)
        self._fill_refs()
        self._fill_flow()
        self.status.setText("")

    def _project_url(self) -> str:
        from src import projects

        project = projects.current()
        return project.flow_url if project is not None else ""

    def _fill_flow(self) -> None:
        char = self.store.get(self._current)
        if not char:
            return
        here = self._project_url()
        lines = []
        if here and here in char.flow:
            lines.append(tr("char_flow_here", name=char.flow[here]))
        others = [u for u in char.flow if u != here]
        if others:
            lines.append(tr("char_flow_other", count=len(others)))
        self.flow_label.setText(" ".join(lines) or tr("char_flow_none"))
        self.flow_label.setToolTip("\n".join(f"{n}: {u}" for u, n in char.flow.items()))

    def _fill_refs(self) -> None:
        self.refs.clear()
        for path in self.store.ref_paths(self._current):
            item = QListWidgetItem(_thumb(path), path.name)
            item.setData(ROLE_ID, path.name)
            item.setToolTip(str(path))
            self.refs.addItem(item)

    # ---- actions -----------------------------------------------------
    def new_character(self, name: str = "") -> str:
        base = name or tr(self._k("default_name"))
        taken = {c.name for c in self.store.all()}
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base} {n}", n + 1
        char = self.store.add(candidate)
        self.reload(char.id)
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        return char.id

    def save_current(self) -> None:
        if not self._current:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText(tr("char_name_required"))
            return
        other = self.store.by_name(name)
        if other and other.id != self._current:
            self.status.setText(tr(self._k("name_taken"), name=name))
            return
        self.store.update(self._current, name=name, notes=self.notes_edit.toPlainText(),
                          voice=self.voice_combo.currentData() or "")
        self.reload(self._current)
        self.status.setText(tr("char_saved"))
        log.info(tr(self._k("saved_log"), name=name))

    def delete_current(self, confirm: bool = True) -> None:
        char = self.store.get(self._current)
        if not char:
            return
        if confirm and QMessageBox.question(self, tr("char_delete"), tr(self._k("delete_confirm"), name=char.name)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(char.id)
        self._current = ""
        self.reload()

    def add_images_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, tr("char_add_refs"), "", f"Images ({exts})")
        if files:
            self.add_images([Path(f) for f in files])

    def add_images(self, paths: list[Path]) -> int:
        if not self._current:
            return 0
        added = self.store.add_refs(self._current, paths)
        self.reload(self._current)
        return len(added)

    def remove_selected_refs(self) -> int:
        names = [i.data(ROLE_ID) for i in self.refs.selectedItems()]
        for name in names:
            self.store.remove_ref(self._current, name)
        if names:
            self.reload(self._current)
        return len(names)

    # ---- Google Flow (Phase 14b) ---------------------------------------
    def setup_in_flow(self) -> None:
        """Create (or copy) the selected entry in the active project's Flow project."""
        char = self.store.get(self._current)
        if not char:
            return
        self.save_current()
        self.btn_flow.setEnabled(False)
        self.status.setText(tr("char_flow_running", name=char.name))
        entry_id, kind = char.id, self.kind

        def work() -> None:
            try:
                self._flow_setup(kind, entry_id)
                self._signals.flow_done.emit(entry_id, "")
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self._signals.flow_done.emit(entry_id, str(exc) or type(exc).__name__)

        threading.Thread(target=work, name="flow-character", daemon=True).start()

    def _flow_done(self, entry_id: str, error: str) -> None:
        self.btn_flow.setEnabled(True)
        char = self.store.get(entry_id)
        if error:
            self.status.setText(tr("char_flow_failed", error=error))
            log.error(tr("char_flow_failed", error=error))
        elif char is not None:
            self.status.setText(tr("char_flow_done", name=char.name))
            log.info(tr("char_flow_done", name=char.name))
        if entry_id == self._current:
            self._fill_flow()

    # ---- voice preview -------------------------------------------------
    def _preview_path(self, voice: str) -> Path:
        return self.store.root / "_previews" / f"{voice}.wav"

    def preview(self) -> None:
        voice = self.voice_combo.currentData() or ""
        if not voice:
            self.status.setText(tr("char_pick_voice"))
            return
        cached = self._preview_path(voice)
        if cached.is_file():
            self._play(cached)
            return
        self.btn_preview.setEnabled(False)
        self.status.setText(tr("char_preview_running", voice=voice))

        def work() -> None:
            try:
                wav = preview_voice(voice, PREVIEW_TEXT, self._key_source, self._transport)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(wav)
                self._signals.done.emit(str(cached), "")
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self._signals.done.emit("", str(exc))

        threading.Thread(target=work, name="voice-preview", daemon=True).start()

    def _preview_done(self, path: str, error: str) -> None:
        self.btn_preview.setEnabled(True)
        if error:
            self.status.setText(error)
            log.error(tr("char_preview_failed", error=error))
            return
        self.status.setText("")
        self._play(Path(path))

    def _play(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            if self._player is None:
                self._player = QMediaPlayer(self)
                self._player.setAudioOutput(QAudioOutput(self._player))
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.play()
        except ImportError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
