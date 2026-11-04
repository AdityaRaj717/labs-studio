"""Inspector tab: a run's voice (Fish Audio), music and effects (Stable Audio 3), and the files already made."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from src.i18n import tr

FREE_VOICE_MODEL = "s2.1-pro-free"
VOICE_MODELS = (FREE_VOICE_MODEL, "s2.1-pro", "s2-pro", "s1", "drama-3")  # the engine's audio_voice_generate enum
SOUND_KINDS = ("music", "sfx")


class AudioPanel(QWidget):
    """Asks; the page calls the engine and confirms spend. Nothing here talks to the engine itself."""

    voices_requested = Signal()
    voice_requested = Signal(dict)
    estimate_requested = Signal(dict)
    sound_requested = Signal(dict)
    play_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.voice_text = QPlainTextEdit()
        self.voice_text.setPlaceholderText(tr("audio_voice_text"))
        self.voice_text.setFixedHeight(72)
        self.voice_combo = QComboBox()
        self.voice_combo.addItem(tr("audio_voice_default"), None)
        self.btn_voices = QPushButton(tr("audio_voice_list"))
        self.btn_voices.clicked.connect(self.voices_requested.emit)
        self.model_combo = QComboBox()
        for model in VOICE_MODELS:
            self.model_combo.addItem(model if model == FREE_VOICE_MODEL else tr("audio_paid_model", model=model), model)
        self.btn_voice = QPushButton(tr("audio_voice_make"))
        self.btn_voice.clicked.connect(self._ask_voice)

        self.kind_combo = QComboBox()
        for kind in SOUND_KINDS:
            self.kind_combo.addItem(tr(f"audio_kind_{kind}"), kind)
        self.sound_prompt = QLineEdit()
        self.sound_prompt.setPlaceholderText(tr("audio_sound_prompt"))
        self.duration = QSpinBox()
        self.duration.setRange(1, 380)
        self.duration.setValue(20)
        self.duration.setSuffix(" s")
        self.btn_estimate = QPushButton(tr("audio_estimate"))
        self.btn_estimate.clicked.connect(lambda: self.estimate_requested.emit(self.sound_args()))
        self.btn_sound = QPushButton(tr("audio_sound_make"))
        self.btn_sound.setEnabled(False)  # an estimate comes first
        self.btn_sound.clicked.connect(lambda: self.sound_requested.emit(self.sound_args()))
        self.estimate_label = QLabel("")
        self.estimate_label.setWordWrap(True)
        for field in (self.kind_combo.currentIndexChanged, self.sound_prompt.textChanged, self.duration.valueChanged):
            field.connect(self._clear_estimate)

        self.files = QListWidget()
        self.files.itemActivated.connect(lambda item: self.play_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.note = QLabel(tr("audio_none"))
        self.note.setWordWrap(True)
        self.note.setObjectName("Muted")

        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.btn_voices)
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.kind_combo)
        sound_row.addWidget(self.duration)
        make_row = QHBoxLayout()
        make_row.addWidget(self.btn_estimate)
        make_row.addWidget(self.btn_sound)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)
        box.addWidget(QLabel(tr("audio_voice_heading")))
        box.addWidget(self.voice_text)
        box.addLayout(voice_row)
        box.addWidget(self.model_combo)
        box.addWidget(self.btn_voice)
        box.addSpacing(8)
        box.addWidget(QLabel(tr("audio_sound_heading")))
        box.addLayout(sound_row)
        box.addWidget(self.sound_prompt)
        box.addLayout(make_row)
        box.addWidget(self.estimate_label)
        box.addSpacing(8)
        box.addWidget(QLabel(tr("audio_files_heading")))
        box.addWidget(self.files, 1)
        box.addWidget(self.note)

    def voice_args(self) -> dict[str, Any]:
        args = {"text": self.voice_text.toPlainText().strip(), "model": self.model_combo.currentData()}
        if self.voice_combo.currentData():
            args["voice_id"] = self.voice_combo.currentData()
        return args

    def sound_args(self) -> dict[str, Any]:
        return {"kind": self.kind_combo.currentData(), "prompt": self.sound_prompt.text().strip(),
                "duration": self.duration.value()}

    def _ask_voice(self) -> None:
        if self.voice_args()["text"]:
            self.voice_requested.emit(self.voice_args())

    def _clear_estimate(self) -> None:
        self.btn_sound.setEnabled(False)
        self.estimate_label.setText("")

    def show_estimate(self, credits: int) -> None:
        self.estimate_label.setText(tr("audio_estimate_is", credits=credits))
        self.btn_sound.setEnabled(bool(self.sound_args()["prompt"]))

    def show_voices(self, voices: list[dict[str, Any]]) -> None:
        keep = self.voice_combo.currentData()
        self.voice_combo.clear()
        self.voice_combo.addItem(tr("audio_voice_default"), None)
        for voice in voices:
            self.voice_combo.addItem(str(voice.get("title") or voice.get("voice_id")), voice.get("voice_id"))
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(keep)))

    def show_files(self, audio: list[dict[str, Any]]) -> None:
        """The engine's list for the run, as it stands: nothing is kept here that the engine didn't say."""
        self.files.clear()
        for entry in audio:
            path = Path(str(entry.get("file") or ""))
            item = QListWidgetItem(f"{tr('audio_kind_' + str(entry.get('kind')))}  {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(" · ".join(str(entry[k]) for k in ("provider", "model") if entry.get(k)))
            self.files.addItem(item)
        self.note.setText(tr("audio_play_hint") if audio else tr("audio_none"))

    def set_busy(self, busy: bool, message: str = "") -> None:
        for b in (self.btn_voice, self.btn_voices, self.btn_estimate):
            b.setEnabled(not busy)
        if busy:
            self.btn_sound.setEnabled(False)
        self.note.setText(message or (tr("audio_play_hint") if self.files.count() else tr("audio_none")))
