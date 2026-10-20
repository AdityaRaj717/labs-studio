"""Export off the GUI thread: a QThread worker around ``editor.ffmpeg.run_export``, and the
dialog that shows progress and cancels it."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from src.editor import ffmpeg as ff
from src.editor.model import Project
from src.i18n import tr

log = logging.getLogger(__name__)


class ExportWorker(QObject):
    progress = Signal(float)
    finished = Signal(str)   # output path
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, exe: str, plan: ff.ExportPlan, workdir: Path, popen=None):
        super().__init__()
        self.exe, self.plan, self.workdir = exe, plan, workdir
        self._stop = threading.Event()
        self._popen = popen

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        kw = {"popen": self._popen} if self._popen else {}
        try:
            out = ff.run_export(self.exe, self.plan, self.workdir, on_progress=self.progress.emit,
                                should_stop=self._stop.is_set, **kw)
        except ff.ExportCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            log.exception("Export failed")
            self.failed.emit(str(exc))
        else:
            self.finished.emit(str(out))


class ExportDialog(QDialog):
    QUALITY = [("ed_q_high", 18), ("ed_q_normal", 21), ("ed_q_small", 26)]
    PRESETS = ["veryfast", "fast", "medium", "slow"]

    def __init__(self, project: Project, exe: str, default_path: str, workdir: Path,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("ed_export_title"))
        self.setMinimumWidth(520)
        self.project, self.exe, self.workdir = project, exe, workdir
        self.thread: QThread | None = None
        self.worker: ExportWorker | None = None
        self.output: str | None = None

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)
        row = QHBoxLayout()
        self.path = QLineEdit(default_path)
        browse = QPushButton(tr("ed_browse"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow(tr("ed_export_file"), row)
        self.quality = QComboBox()
        for key, crf in self.QUALITY:
            self.quality.addItem(tr(key), crf)
        self.quality.setCurrentIndex(1)
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS)
        self.preset.setCurrentText("medium")
        self.srt = QCheckBox(tr("ed_export_srt"))
        self.srt.setEnabled(bool(project.cues))
        form.addRow(tr("ed_quality"), self.quality)
        form.addRow(tr("ed_speed"), self.preset)
        form.addRow("", self.srt)
        info = QLabel(tr("ed_export_info", w=project.width, h=project.height, fps=project.fps,
                         dur=f"{project.duration:.1f}"))
        info.setObjectName("StatsHeader")
        lay.addWidget(info)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(self.status.textInteractionFlags() |
                                            self.status.textInteractionFlags().TextSelectableByMouse)
        lay.addWidget(self.status)
        self.buttons = QDialogButtonBox()
        self.btn_start = self.buttons.addButton(tr("ed_export_start"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_open = self.buttons.addButton(tr("ed_open_folder"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_open.setVisible(False)
        self.btn_close = self.buttons.addButton(tr("ed_close"), QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.start)
        self.buttons.rejected.connect(self.cancel_or_close)
        self.btn_open.clicked.connect(self._open_folder)
        lay.addWidget(self.buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("ed_export_file"), self.path.text(), "MP4 (*.mp4)")
        if path:
            self.path.setText(path)

    def _open_folder(self) -> None:
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output).parent)))

    def running(self) -> bool:
        return self.thread is not None

    def start(self) -> None:
        if self.running():
            return
        out = self.path.text().strip()
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        missing = ff.missing_sources(self.project)
        if missing:
            self.status.setText(tr("ed_missing_files", files="\n".join(missing[:8])))
            return
        settings = ff.ExportSettings(crf=self.quality.currentData(), preset=self.preset.currentText(),
                                     write_srt=self.srt.isChecked())
        try:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            plan = ff.build_export(self.project, out, settings)
        except (ff.ExportError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.status.setText(tr("ed_exporting"))
        self.btn_start.setEnabled(False)
        self.btn_open.setVisible(False)
        self.btn_close.setText(tr("ed_cancel"))
        self.thread = QThread(self)
        self.worker = ExportWorker(self.exe, plan, self.workdir)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.worker.finished.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.thread.start()

    def _end(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_close.setText(tr("ed_close"))

    def _done(self, path: str) -> None:
        self._end()
        self.output = path
        self.bar.setValue(1000)
        self.status.setText(tr("ed_export_done", path=path))
        self.btn_open.setVisible(True)
        log.info("Exported %s", path)

    def _failed(self, msg: str) -> None:
        self._end()
        self.status.setText(tr("ed_export_failed", error=msg))

    def _cancelled(self) -> None:
        self._end()
        self.bar.setVisible(False)
        self.status.setText(tr("ed_export_cancelled"))

    def cancel_or_close(self) -> None:
        if self.running():
            self.status.setText(tr("ed_cancelling"))
            self.worker.stop()
        else:
            self.reject()

    def closeEvent(self, ev) -> None:  # noqa: N802
        if self.running():
            self.worker.stop()
            ev.ignore()
        else:
            super().closeEvent(ev)

    def shutdown(self) -> None:
        if self.running():
            self.worker.stop()
            self.thread.quit()
            self.thread.wait(8000)


class AutoEditDialog(QDialog):
    """Folder of images/clips → slideshow options."""

    def __init__(self, folder: str = "", music: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        from src.editor.autoedit import SlideshowOptions

        self.setWindowTitle(tr("ed_autoedit_title"))
        self.setMinimumWidth(480)
        d = SlideshowOptions()
        form = QFormLayout(self)
        self.folder = QLineEdit(folder)
        form.addRow(tr("ed_ae_folder"), self._with_browse(self.folder, self._pick_folder))
        self.music = QLineEdit(music)
        self.music.setPlaceholderText(tr("ed_ae_music_none"))
        form.addRow(tr("ed_ae_music"), self._with_browse(self.music, self._pick_music))
        self.image_duration = QSpinBox()
        self.image_duration.setRange(1, 60)
        self.image_duration.setSuffix(" s")
        self.image_duration.setValue(int(d.image_duration))
        self.transition = QComboBox()
        for v in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
            self.transition.addItem(f"{v:g} s", v)
        self.transition.setCurrentIndex(2)
        self.max_clip = QSpinBox()
        self.max_clip.setRange(0, 600)
        self.max_clip.setSuffix(" s")
        self.max_clip.setSpecialValueText(tr("ed_ae_full"))
        self.music_volume = QSpinBox()
        self.music_volume.setRange(0, 200)
        self.music_volume.setSuffix(" %")
        self.music_volume.setValue(int(d.music_volume * 100))
        self.keep_audio = QCheckBox(tr("ed_ae_keep_audio"))
        self.keep_audio.setChecked(True)
        form.addRow(tr("ed_ae_image_dur"), self.image_duration)
        form.addRow(tr("ed_ae_transition"), self.transition)
        form.addRow(tr("ed_ae_max_clip"), self.max_clip)
        form.addRow(tr("ed_ae_music_vol"), self.music_volume)
        form.addRow("", self.keep_audio)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _with_browse(self, edit: QLineEdit, slot) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        b = QPushButton(tr("ed_browse"))
        b.clicked.connect(slot)
        h.addWidget(b)
        return w

    def _pick_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("ed_ae_folder"), self.folder.text())
        if d:
            self.folder.setText(d)

    def _pick_music(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, tr("ed_ae_music"), self.music.text(),
                                           "Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac *.opus)")
        if f:
            self.music.setText(f)

    def options(self):
        from src.editor.autoedit import SlideshowOptions

        return SlideshowOptions(
            image_duration=float(self.image_duration.value()), transition=self.transition.currentData(),
            max_clip=float(self.max_clip.value()), music=self.music.text().strip(),
            music_volume=self.music_volume.value() / 100, keep_clip_audio=self.keep_audio.isChecked())
