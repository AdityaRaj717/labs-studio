"""Settings → Tools: where ffmpeg, ffprobe and Real-ESRGAN live (blank = use PATH)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from src import config
from src.i18n import tr
from src.tools import binaries
from src.tools.tasks import TOOL_NAMES


class BinaryRow(QWidget):
    def __init__(self, tool: str, store, parent: QWidget | None = None):
        super().__init__(parent)
        self.tool = tool
        self.store = store
        self.edit = QLineEdit(store.get(binaries.setting_key(tool), "") or "")
        self.edit.setPlaceholderText(tr("tools_path_placeholder"))
        self.edit.editingFinished.connect(self.save)
        browse = QPushButton(tr("gen_browse"))
        browse.clicked.connect(self._browse)
        self.status = QLabel()
        self.status.setObjectName("PageBody")
        self.status.setWordWrap(True)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(browse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.refresh()

    def _browse(self) -> None:
        filt = "Programs (*.exe)" if sys.platform == "win32" else ""
        path, _ = QFileDialog.getOpenFileName(self, TOOL_NAMES[self.tool], self.edit.text(), filt)
        if path:
            self.edit.setText(path)
            self.save()

    def save(self) -> None:
        self.store.set(binaries.setting_key(self.tool), self.edit.text().strip())
        self.refresh()

    def refresh(self) -> None:
        found = binaries.find_binary(self.tool, self.store)
        if found:
            self.status.setText(tr("tools_found", path=str(found)))
        else:
            self.status.setText(tr("tools_not_found"))


class ToolsTab(QWidget):
    def __init__(self, store=None, parent: QWidget | None = None):
        super().__init__(parent)
        store = store if store is not None else config.settings()
        intro = QLabel(tr("tools_intro"))
        intro.setWordWrap(True)
        intro.setObjectName("PageBody")
        form = QFormLayout()
        self.rows = {}
        for tool in binaries.TOOL_IDS:
            self.rows[tool] = BinaryRow(tool, store)
            form.addRow(TOOL_NAMES[tool], self.rows[tool])
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addStretch(1)
