"""Stand-in page for every screen that later phases will build."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from src.i18n import tr
from src.ui.kit import page_layout, page_title


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title

        title_label = page_title(title)
        body = QLabel(tr("placeholder_body"))
        body.setObjectName("PageBody")

        layout = page_layout(self)
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(body, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
