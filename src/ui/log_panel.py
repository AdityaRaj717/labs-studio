"""Logging setup and the "Detailed Log" page.

``QtLogHandler`` keeps a ring buffer of formatted lines and re-emits each one
through a Qt signal, so records logged from any thread land on the GUI thread.
The handler is installed at startup (before the page exists), and the page
replays the buffer when it is first built.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from src.i18n import tr
from src.ui.kit import header_row, page_layout, set_icon

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"
MAX_LINES = 5000


class _Emitter(QObject):
    line = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, max_lines: int = MAX_LINES):
        super().__init__()
        self.emitter = _Emitter()
        self.buffer: deque[str] = deque(maxlen=max_lines)
        self._buffer_lock = threading.Lock()
        self.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            self.handleError(record)
            return
        with self._buffer_lock:
            self.buffer.append(text)
        self.emitter.line.emit(text)

    def snapshot(self) -> list[str]:
        with self._buffer_lock:
            return list(self.buffer)


_qt_handler: QtLogHandler | None = None
_log_file: Path | None = None


def setup_logging(log_dir: Path, level: int = logging.INFO) -> QtLogHandler:
    """Send logs to stderr, ``<log_dir>/latest.log`` and the in-app log page."""
    global _qt_handler, _log_file
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = log_dir / "latest.log"

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = logging.FileHandler(_log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    _qt_handler = QtLogHandler()

    for h in (file_handler, stream_handler, _qt_handler):
        root.addHandler(h)
    return _qt_handler


def log_file_path() -> Path | None:
    return _log_file


class LogPanel(QWidget):
    """Live, read-only view of everything the app logs."""

    def __init__(self, handler: QtLogHandler | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.handler = handler or _qt_handler

        clear_btn = QPushButton(tr("log_clear"))
        set_icon(clear_btn, "eraser")
        open_btn = QPushButton(tr("log_open_file"))
        set_icon(open_btn, "folder-open")
        open_btn.setEnabled(log_file_path() is not None)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        layout = page_layout(self)
        layout.addLayout(header_row(tr("nav_log"), open_btn, clear_btn))
        layout.addWidget(self.view, 1)

        clear_btn.clicked.connect(self.view.clear)
        open_btn.clicked.connect(self._open_log_file)

        if self.handler is not None:
            for line in self.handler.snapshot():
                self.view.appendPlainText(line)
            self.handler.emitter.line.connect(self.append_line, Qt.ConnectionType.QueuedConnection)

    def append_line(self, text: str) -> None:
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        self.view.appendPlainText(text)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _open_log_file(self) -> None:
        path = log_file_path()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
