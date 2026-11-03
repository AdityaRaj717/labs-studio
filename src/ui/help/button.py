"""Small "?" button pinned to a page's top-right corner (Phase 15).

``MainWindow.page()`` adds one to every page that has a help topic, so the
pages themselves don't change.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QPushButton, QWidget

from src.i18n import tr
from src.ui.kit import set_icon

SIZE = 28
MARGIN = 6


class HelpButton(QPushButton):
    def __init__(self, topic: str, on_click: Callable[[str], None], parent: QWidget):
        super().__init__(parent)
        set_icon(self, "question")
        self.setAccessibleName(tr("help_button_tip"))
        self.topic = topic
        self.setObjectName("HelpButton")
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("help_button_tip"))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(lambda: on_click(self.topic))
        parent.installEventFilter(self)
        self._place()
        self.raise_()

    def set_on_black(self, on: bool) -> None:
        """Over the black viewer the ink is the frame's, else the page's."""
        set_icon(self, "question", "frame_text" if on else "text")

    def _place(self) -> None:
        page = self.parentWidget()
        self.move(page.width() - SIZE - MARGIN, MARGIN)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() not in (QEvent.Type.Resize, QEvent.Type.Show):
            return False
        try:
            if obj is self.parentWidget():
                self._place()
                self.raise_()
        except RuntimeError:  # page or button already deleted on the C++ side during teardown
            pass
        return False


def attach_help_button(page: QWidget, topic: str, on_click: Callable[[str], None]) -> HelpButton:
    btn = HelpButton(topic, on_click, page)
    page.help_button = btn
    return btn
