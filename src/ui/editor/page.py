"""Video Editor page: toolbar, preview, side panels, timeline, ffmpeg status."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from src.editor import ffmpeg as ff
from src.editor.autoedit import build_slideshow, scan_folder
from src.editor.model import PROJECT_EXT, Clip, Project, media_kind
from src.editor.subtitles import load_subtitles, write_srt
from src.i18n import tr
from src.ui.editor.export import AutoEditDialog, ExportDialog
from src.ui.editor.panels import ClipInspector, ProjectPanel, SubtitlePanel
from src.ui.editor.preview import PreviewWidget
from src.ui.editor.timeline import TimelineWidget

log = logging.getLogger(__name__)

MEDIA_FILTER = ("Media (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.mov *.webm *.mkv *.avi *.m4v "
                "*.mp3 *.wav *.m4a *.aac *.ogg *.flac *.opus)")
UNDO_LIMIT = 100


def _fmt(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"


class VideoEditorPage(QWidget):
    def __init__(self, store=None, parent: QWidget | None = None):
        super().__init__(parent)
        if store is None:
            from src import config

            store = config.settings()
        self.store = store
        self.project = Project.new()
        self.path: Path | None = None
        self.dirty = False
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._snap_pending = False
        self.exe: str | None = None
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        title = QLabel(tr("nav_video_editor"))
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(self._build_ffmpeg_bar())
        root.addLayout(self._build_toolbar())

        self.preview = PreviewWidget(self.project)
        self.inspector = ClipInspector()
        self.subs = SubtitlePanel()
        self.project_panel = ProjectPanel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll(self.inspector), tr("ed_tab_clip"))
        self.tabs.addTab(self.subs, tr("ed_tab_subtitles"))
        self.tabs.addTab(self._scroll(self.project_panel), tr("ed_tab_project"))
        self.tabs.setMinimumWidth(340)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.preview)
        top.addWidget(self.tabs)
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)

        self.timeline = TimelineWidget(self.project)
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidget(self.timeline)
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fit_timeline(self.timeline.height())
        self.timeline.heightChanged.connect(self._fit_timeline)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(top)
        vsplit.addWidget(self.timeline_scroll)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        root.addWidget(vsplit, 1)
        self.status = QLabel("")
        self.status.setObjectName("StatsHeader")
        root.addWidget(self.status)

        # wiring
        self.timeline.clipSelected.connect(self._on_clip_selected)
        self.timeline.playheadMoved.connect(self._on_playhead)
        self.timeline.aboutToEdit.connect(self.snapshot)
        self.timeline.edited.connect(self._after_edit)
        self.timeline.cueSelected.connect(self._on_cue_selected)
        self.timeline.contextRequested.connect(self._context_menu)
        for panel in (self.inspector, self.subs, self.project_panel):
            panel.aboutToEdit.connect(self._snapshot_once)
            panel.edited.connect(self._after_panel_edit)
        self.subs.importRequested.connect(self.import_subtitles)
        self.subs.exportRequested.connect(self.export_srt)
        self.subs.seekRequested.connect(lambda t: self.timeline.set_playhead(t))

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)
        self._play_timer.timeout.connect(self._tick)
        self._play_clock = 0.0

        for seq, slot in [("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                          ("Ctrl+S", self.save), ("Space", self.toggle_play), ("S", self.split),
                          ("Delete", self.delete_selected)]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self._set_project(self.project)
        self.refresh_ffmpeg()

    # ---- building --------------------------------------------------------
    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidget(w)
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.Shape.NoFrame)
        return s

    def _build_ffmpeg_bar(self) -> QWidget:
        bar = QFrame()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setWordWrap(True)
        self.ffmpeg_path = QLineEdit(self.store.get(ff.SETTINGS_KEY, "") or "")
        self.ffmpeg_path.setPlaceholderText(tr("ed_ffmpeg_placeholder"))
        btn_browse = QPushButton(tr("ed_browse"))
        btn_browse.clicked.connect(self._browse_ffmpeg)
        btn_check = QPushButton(tr("ed_ffmpeg_check"))
        btn_check.clicked.connect(self._save_ffmpeg_path)
        self.ffmpeg_path.returnPressed.connect(self._save_ffmpeg_path)
        h.addWidget(self.ffmpeg_label, 1)
        h.addWidget(self.ffmpeg_path, 1)
        h.addWidget(btn_browse)
        h.addWidget(btn_check)
        self.ffmpeg_bar = bar
        return bar

    def _button(self, key: str, slot, primary: bool = False) -> QPushButton:
        b = QPushButton(tr(key))
        b.clicked.connect(slot)
        if primary:
            b.setObjectName("PrimaryButton")
        return b

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        file_btn = QToolButton()
        file_btn.setText(tr("ed_file"))
        file_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(file_btn)
        m.addAction(tr("ed_new"), self.new_project)
        m.addAction(tr("ed_open"), self.open_project)
        m.addAction(tr("ed_save"), self.save)
        m.addAction(tr("ed_save_as"), self.save_as)
        file_btn.setMenu(m)
        row.addWidget(file_btn)
        row.addWidget(self._button("ed_add_media", self.add_media))
        row.addWidget(self._button("ed_add_text", self.add_text))
        track_btn = QToolButton()
        track_btn.setText(tr("ed_add_track"))
        track_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tm = QMenu(track_btn)
        for kind in ("video", "overlay", "audio"):
            tm.addAction(tr(f"ed_track_{kind}"), lambda k=kind: self.add_track(k))
        track_btn.setMenu(tm)
        row.addWidget(track_btn)
        row.addWidget(self._button("ed_autoedit", self.auto_edit))
        row.addSpacing(12)
        row.addWidget(self._button("ed_split", self.split))
        row.addWidget(self._button("ed_delete", self.delete_selected))
        row.addWidget(self._button("ed_undo", self.undo))
        row.addWidget(self._button("ed_redo", self.redo))
        row.addSpacing(12)
        self.btn_play = self._button("ed_play", self.toggle_play)
        row.addWidget(self.btn_play)
        self.time_label = QLabel("00:00.00 / 00:00.00")
        row.addWidget(self.time_label)
        row.addWidget(self._button("ed_zoom_out", lambda: self.timeline.set_zoom(self.timeline.pps / 1.5)))
        row.addWidget(self._button("ed_zoom_in", lambda: self.timeline.set_zoom(self.timeline.pps * 1.5)))
        row.addStretch(1)
        self.btn_export = self._button("ed_export", self.export, primary=True)
        row.addWidget(self.btn_export)
        return row

    def _fit_timeline(self, h: int) -> None:
        """Show every lane (up to ~6 tracks) without a vertical scrollbar."""
        self.timeline_scroll.setMinimumHeight(min(h + 18, 360))

    # ---- ffmpeg ------------------------------------------------------------
    def refresh_ffmpeg(self) -> None:
        self.exe = ff.find_ffmpeg(self.store.get(ff.SETTINGS_KEY, "") or None)
        version = ff.ffmpeg_version(self.exe) if self.exe else None
        if self.exe and version:
            self.ffmpeg_label.setText(tr("ed_ffmpeg_ok", version=version.split("-")[0]))
            self.ffmpeg_label.setToolTip(self.exe)
            self.ffmpeg_label.setObjectName("StatsHeader")
        else:
            self.exe = None
            self.ffmpeg_label.setText(tr("ed_ffmpeg_missing"))
            self.ffmpeg_label.setToolTip("")
            self.ffmpeg_label.setObjectName("DemoBanner")
        self.ffmpeg_label.style().unpolish(self.ffmpeg_label)
        self.ffmpeg_label.style().polish(self.ffmpeg_label)
        self.btn_export.setEnabled(self.exe is not None)
        self.btn_export.setToolTip("" if self.exe else tr("ed_ffmpeg_missing"))

    def _browse_ffmpeg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "ffmpeg", self.ffmpeg_path.text(), "ffmpeg (ffmpeg.exe ffmpeg)")
        if f:
            self.ffmpeg_path.setText(f)
            self._save_ffmpeg_path()

    def _save_ffmpeg_path(self) -> None:
        self.store.set(ff.SETTINGS_KEY, self.ffmpeg_path.text().strip())
        self.refresh_ffmpeg()

    def probe(self, path: str) -> ff.MediaInfo:
        return ff.probe(self.exe, path) if self.exe else ff.MediaInfo()

    # ---- project / undo -----------------------------------------------------
    def _set_project(self, project: Project) -> None:
        self.project = project
        self.timeline.set_project(project)
        self.preview.set_project(project)
        self.subs.set_project(project)
        self.project_panel.set_project(project)
        self.inspector.set_clip(None, None)
        self._update_status()

    def snapshot(self) -> None:
        self._undo.append(self.project.to_dict())
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _snapshot_once(self) -> None:
        """Panels emit aboutToEdit per keystroke/spin step; take one snapshot per burst."""
        if not self._snap_pending:
            self.snapshot()
            self._snap_pending = True
            QTimer.singleShot(800, lambda: setattr(self, "_snap_pending", False))

    def _restore(self, data: dict) -> None:
        self.project = Project.from_dict(data)
        self._set_project(self.project)
        self._mark_dirty()

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.project.to_dict())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.project.to_dict())
            self._restore(self._redo.pop())

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_status()

    def _after_edit(self) -> None:
        self.timeline.relayout()
        self.preview.update()
        self._mark_dirty()

    def _after_panel_edit(self) -> None:
        self.timeline.relayout()
        self.preview.update()
        self.subs.playhead = self.timeline.playhead
        self._mark_dirty()

    def _update_status(self) -> None:
        name = self.path.name if self.path else tr("ed_untitled")
        n = sum(len(t.clips) for t in self.project.tracks)
        self.status.setText(tr("ed_status", name=name + (" *" if self.dirty else ""), clips=n,
                               cues=len(self.project.cues), w=self.project.width, h=self.project.height,
                               fps=self.project.fps))
        self.time_label.setText(f"{_fmt(self.timeline.playhead)} / {_fmt(self.project.duration)}")

    # ---- selection / playhead ------------------------------------------------
    def _on_clip_selected(self, clip: Clip | None) -> None:
        self.inspector.set_clip(clip, self.project.find(clip) if clip else None)
        if clip is not None:
            self.tabs.setCurrentIndex(0)

    def _on_cue_selected(self, cue) -> None:
        self.tabs.setCurrentIndex(1)
        self.subs.select_cue(cue)

    def _on_playhead(self, t: float) -> None:
        self.preview.set_time(t)
        self.subs.playhead = t
        self.time_label.setText(f"{_fmt(t)} / {_fmt(self.project.duration)}")

    def toggle_play(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.btn_play.setText(tr("ed_play"))
            return
        if self.timeline.playhead >= self.project.duration:
            self.timeline.set_playhead(0.0)
        self._play_clock = time.monotonic()
        self._play_timer.start()
        self.btn_play.setText(tr("ed_pause"))

    def _tick(self) -> None:
        now = time.monotonic()
        t = self.timeline.playhead + (now - self._play_clock)
        self._play_clock = now
        if t >= self.project.duration:
            t = self.project.duration
            self.toggle_play()
        self.timeline.set_playhead(t)
        x = int(self.timeline.x_of(t))
        self.timeline_scroll.ensureVisible(x, 0, 80, 0)

    # ---- edits --------------------------------------------------------------
    def add_files(self, paths: list[str]) -> int:
        added = 0
        self.snapshot()
        for path in paths:
            kind = media_kind(path)
            if kind is None:
                continue
            if kind == "audio":
                info = self.probe(path)
                track = self.project.first_track("audio")
                clip = Clip("audio", path, duration=round(info.duration or 10.0, 3),
                            source_duration=info.duration)
                self.project.append_clip(track, clip)
            else:
                track = self.project.first_track("video")
                clip = Clip(kind, path, duration=3.0)
                if kind == "video":
                    info = self.probe(path)
                    clip.source_duration = info.duration
                    clip.has_audio = info.has_audio
                    clip.duration = round(info.duration or 5.0, 3)
                self.project.append_clip(track, clip)
            added += 1
        if added:
            self._after_edit()
        else:
            self._undo.pop()
        return added

    def add_media(self) -> None:
        start = self.store.get("editor.last_dir", "") or ""
        files, _ = QFileDialog.getOpenFileNames(self, tr("ed_add_media"), start, MEDIA_FILTER)
        if files:
            self.store.set("editor.last_dir", str(Path(files[0]).parent))
            self.add_files(files)

    def add_text(self) -> None:
        self.snapshot()
        track = self.project.first_track("overlay")
        t = self.timeline.playhead
        clip = Clip("text", start=round(t, 3), duration=3.0, text=tr("ed_text_default"), x=0.5, y=0.15,
                    font_size=72)
        track.clips.append(clip)
        self._after_edit()
        self.timeline.select(clip)

    def add_track(self, kind: str) -> None:
        self.snapshot()
        self.project.add_track(kind)
        self._after_edit()

    def split(self) -> None:
        clip = self.timeline.selected
        if clip is None:
            # split whatever sits under the playhead on the first visual track
            for track in self.project.tracks:
                for c in track.clips:
                    if c.start < self.timeline.playhead < c.end:
                        clip = c
                        break
                if clip:
                    break
        if clip is None:
            return
        self.snapshot()
        if self.project.split_clip(clip, self.timeline.playhead) is None:
            self._undo.pop()
            return
        self._after_edit()

    def delete_selected(self) -> None:
        clip = self.timeline.selected
        if clip is None:
            return
        self.snapshot()
        self.project.remove_clip(clip)
        self.timeline.select(None)
        self._after_edit()

    def _context_menu(self, clip, gpos, t: float) -> None:
        menu = QMenu(self)
        if clip is not None:
            menu.addAction(tr("ed_split"), self.split)
            menu.addAction(tr("ed_delete"), self.delete_selected)
            menu.addSeparator()
        track_actions = []
        for track in self.project.tracks:
            track_actions.append((track, menu.addAction(tr("ed_remove_track", name=track.name))))
        chosen = menu.exec(gpos)
        for track, act in track_actions:
            if chosen is act:
                self.snapshot()
                self.project.remove_track(track)
                self.timeline.select(None)
                self._after_edit()

    def auto_edit(self) -> None:
        dlg = AutoEditDialog(self.store.get("editor.last_dir", "") or "", parent=self)
        if not dlg.exec():
            return
        folder = dlg.folder.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, tr("ed_autoedit_title"), tr("ed_ae_no_folder"))
            return
        self.store.set("editor.last_dir", folder)
        paths = scan_folder(folder)
        if not paths:
            QMessageBox.warning(self, tr("ed_autoedit_title"), tr("ed_ae_empty"))
            return
        self.snapshot()
        # a fresh timeline that keeps the project settings, subtitle style and cues
        base = Project.new(width=self.project.width, height=self.project.height, fps=self.project.fps,
                           background=self.project.background, style=self.project.style,
                           burn_subtitles=self.project.burn_subtitles)
        base.cues = self.project.cues
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            project = build_slideshow(paths, dlg.options(), probe=self.probe, project=base)
        finally:
            self.unsetCursor()
        self._set_project(project)
        self._mark_dirty()
        log.info("Auto-edit: %d items from %s", len(paths), folder)

    # ---- subtitles ------------------------------------------------------------
    def import_subtitles(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, tr("ed_sub_import"), self.store.get("editor.last_dir", "") or "",
                                           "Subtitles (*.srt *.ass *.ssa)")
        if not f:
            return
        try:
            cues = load_subtitles(f)
        except OSError as exc:
            QMessageBox.warning(self, tr("ed_sub_import"), str(exc))
            return
        if not cues:
            QMessageBox.warning(self, tr("ed_sub_import"), tr("ed_sub_none_found"))
            return
        self.snapshot()
        self.project.cues = cues
        self.subs.refresh()
        self._after_edit()

    def export_srt(self) -> None:
        if not self.project.cues:
            return
        f, _ = QFileDialog.getSaveFileName(self, tr("ed_sub_export"), "", "SubRip (*.srt)")
        if f:
            Path(f).write_text(write_srt(self.project.cues), encoding="utf-8")

    # ---- files ------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, tr("nav_video_editor"), tr("ed_discard"),
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def new_project(self) -> None:
        if self._confirm_discard():
            self.path, self.dirty = None, False
            self._undo.clear()
            self._redo.clear()
            self._set_project(Project.new())

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, tr("ed_open"), self.store.get("editor.last_dir", "") or "",
                                           f"Labs Studio project (*{PROJECT_EXT})")
        if f:
            self.load(f)

    def load(self, path: str | Path) -> None:
        try:
            project = Project.load(path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, tr("ed_open"), str(exc))
            return
        self.path, self.dirty = Path(path), False
        self._undo.clear()
        self._redo.clear()
        self._set_project(project)

    def save(self) -> None:
        if self.path is None:
            self.save_as()
            return
        self.project.save(self.path)
        self.dirty = False
        self._update_status()

    def save_as(self) -> None:
        f, _ = QFileDialog.getSaveFileName(self, tr("ed_save_as"), self.store.get("editor.last_dir", "") or "",
                                           f"Labs Studio project (*{PROJECT_EXT})")
        if f:
            if not f.endswith(PROJECT_EXT):
                f += PROJECT_EXT
            self.path = Path(f)
            self.save()

    # ---- export ----------------------------------------------------------------
    def default_output(self) -> str:
        from src.config import app_data_dir

        folder = Path(self.store.get("editor.export_dir", "") or (app_data_dir() / "outputs" / "video_editor"))
        stem = self.path.stem if self.path else "export"
        n = 1
        while (folder / f"{stem}_{n:03d}.mp4").exists():
            n += 1
        return str(folder / f"{stem}_{n:03d}.mp4")

    def export(self) -> None:
        if self.exe is None:
            QMessageBox.warning(self, tr("ed_export"), tr("ed_ffmpeg_missing"))
            return
        if self.project.duration <= 0:
            QMessageBox.information(self, tr("ed_export"), tr("ed_empty"))
            return
        if self._play_timer.isActive():
            self.toggle_play()
        dlg = ExportDialog(self.project, self.exe, self.default_output(), ff.default_workdir(), self)
        self._export_dialog = dlg
        dlg.exec()
        if dlg.output:
            self.store.set("editor.export_dir", str(Path(dlg.output).parent))
        self._export_dialog = None

    def shutdown(self) -> None:
        self._play_timer.stop()
        dlg = getattr(self, "_export_dialog", None)
        if dlg is not None:
            dlg.shutdown()

    # ---- drag and drop ------------------------------------------------------------
    def dragEnterEvent(self, ev) -> None:  # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        subs = [p for p in paths if Path(p).suffix.lower() in (".srt", ".ass", ".ssa")]
        if subs:
            cues = load_subtitles(subs[0])
            if cues:
                self.snapshot()
                self.project.cues = cues
                self.subs.refresh()
                self._after_edit()
        media = [p for p in paths if media_kind(p)]
        if media:
            self.add_files(media)
