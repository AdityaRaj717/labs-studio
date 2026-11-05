"""Command palette (Ctrl+K): type to reach any page or the current page's actions."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QLabel, QLineEdit, QListWidget, QListWidgetItem, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from src import theme
from src.i18n import tr

Command = tuple[str, Callable[[], None]] | tuple[str, Callable[[], None], str]  # optional third: its key
WIDTH, HEIGHT = 480, 340
ROLE_RUN = Qt.ItemDataRole.UserRole
ROLE_KEY = Qt.ItemDataRole.UserRole + 1


class _KeyDelegate(QStyledItemDelegate):
    """Paints a command's shortcut right-aligned in the muted colour."""

    def paint(self, p, option, index) -> None:
        super().paint(p, option, index)
        key = index.data(ROLE_KEY)
        if key:
            p.save()
            p.setPen(QColor(theme.tokens()["text_muted"]))
            p.drawText(option.rect.adjusted(0, 0, -10, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, key)
            p.restore()


class CommandPalette(QFrame):
    def __init__(self, source: Callable[[], list[Command]], parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Palette")
        self.source = source
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("palette_placeholder"))
        self.edit.setClearButtonEnabled(False)
        self.edit.textChanged.connect(self.refilter)
        self.edit.installEventFilter(self)
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setItemDelegate(_KeyDelegate(self.list))
        self.list.itemClicked.connect(self._run)
        self.none = QLabel(tr("palette_none"))
        self.none.setObjectName("Hint")
        self.none.setContentsMargins(10, 8, 10, 8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.edit)
        layout.addWidget(self.none)
        layout.addWidget(self.list, 1)
        self.hide()

    def open(self) -> None:
        self.commands = self.source()
        self.edit.clear()
        self.refilter("")
        host = self.parentWidget()
        width = min(WIDTH, host.width() - 40)
        self.setGeometry((host.width() - width) // 2, 56, width, min(HEIGHT, host.height() - 80))
        self.show()
        self.raise_()
        self.edit.setFocus()

    def refilter(self, text: str) -> None:
        words = text.lower().split()
        self.list.clear()
        for label, run, *key in self.commands:
            if all(w in label.lower() for w in words):
                item = QListWidgetItem(label)
                item.setData(ROLE_RUN, run)
                item.setData(ROLE_KEY, key[0] if key else "")
                self.list.addItem(item)
        self.none.setVisible(self.list.count() == 0)
        # Nothing armed until something is typed: Enter straight after Ctrl+K must not start a run.
        self.list.setCurrentRow(0 if words and self.list.count() else -1)

    def _run(self, item: QListWidgetItem) -> None:
        run = item.data(ROLE_RUN)
        self.hide()
        run()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.FocusOut and self.isVisible():
            self.hide()
        elif event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                if self.list.count():
                    self.list.setCurrentRow((self.list.currentRow() + step) % self.list.count())
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.list.currentItem() is not None:
                    self._run(self.list.currentItem())
                return True
        return False
