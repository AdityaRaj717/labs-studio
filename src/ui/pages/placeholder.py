"""Stand-in page for every screen that later phases will build."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.i18n import tr


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        body = QLabel(tr("placeholder_body"))
        body.setObjectName("PageBody")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(8)
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(body, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
