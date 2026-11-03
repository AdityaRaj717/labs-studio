"""Small shared widgets: page header, wrapping toolbar, icon buttons, segmented choice."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QHBoxLayout, QLabel, QLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from src import theme
from src.ui import icons

PAGE_MARGIN = 20
HELP_GUTTER = 36  # keeps page headers clear of the "?" button


def page_layout(page: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(page)
    layout.setContentsMargins(PAGE_MARGIN, 14, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(10)
    return layout


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    return label


def intro_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageBody")
    label.setWordWrap(True)
    label.setMaximumWidth(760)
    return label


def header_row(title: str, *right: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, HELP_GUTTER, 0)
    row.setSpacing(8)
    row.addWidget(page_title(title))
    row.addStretch(1)
    for w in right:
        row.addWidget(w)
    return row


class FlowLayout(QLayout):
    """Lays widgets left to right and wraps, so a toolbar never clips a label at narrow widths."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _lay_out(self, rect: QRect, apply: bool) -> int:
        """Items of different heights sit centred on their line."""
        gap = self.spacing()
        lines: list[list] = [[]]
        x = rect.x()
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            width = item.sizeHint().width()
            if x + width > rect.right() + 1 and lines[-1]:
                lines.append([])
                x = rect.x()
            lines[-1].append(item)
            x += width + gap
        y = rect.y()
        for line in lines:
            height = max((i.sizeHint().height() for i in line), default=0)
            x = rect.x()
            for item in line:
                hint = item.sizeHint()
                if apply:
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                x += hint.width() + gap
            y += height + gap
        return y - gap - rect.y()


def flow_row(*widgets: QWidget, spacing: int = 6) -> QWidget:
    holder = QWidget()
    layout = FlowLayout(holder, spacing)
    for w in widgets:
        layout.addWidget(w)
    policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    policy.setHeightForWidth(True)
    holder.setSizePolicy(policy)
    return holder


class IconButton(QToolButton):
    """A square icon-only button whose tint follows the theme. The tooltip names the action."""

    def __init__(self, icon_name: str, tip: str, slot: Callable | None = None, checkable: bool = False,
                 color_token: str = "text", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.icon_name = icon_name
        self.color_token = color_token
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCheckable(checkable)
        self.setFixedSize(28, 28)
        self.setIconSize(icons.ICON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            self.clicked.connect(lambda _checked=False: slot())
        self.refresh_icon()

    def refresh_icon(self) -> None:
        self.setIcon(icons.icon(self.icon_name, theme.tokens()[self.color_token]))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.type() == event.Type.PaletteChange:
            self.refresh_icon()
        super().changeEvent(event)


class Segmented(QWidget):
    """A row of mutually exclusive text choices (filters, view switches)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for key, label in options:
            b = QToolButton()
            b.setObjectName("Segment")
            b.setText(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            layout.addWidget(b)
        self.set_current(current or options[0][0])

    def set_current(self, key: str) -> None:
        self.buttons[key].setChecked(True)

    def current(self) -> str:
        return next((k for k, b in self.buttons.items() if b.isChecked()), "")

    def set_label(self, key: str, label: str) -> None:
        self.buttons[key].setText(label)


def data_font(size: int = 11) -> QFont:
    f = QFont("Cascadia Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(size)
    return f


def set_icon(button: QAbstractButton, name: str, token: str = "text") -> None:
    """Give a text button an icon that follows the theme."""
    button.setProperty("icon_name", name)
    button.setProperty("icon_token", token)
    button.setIcon(icons.icon(name, theme.tokens()[token]))


def repolish_tree() -> None:
    """Icons are tinted from tokens, so they are redrawn after a theme switch."""
    for w in QApplication.allWidgets():
        if isinstance(w, IconButton):
            w.refresh_icon()
        elif isinstance(w, QAbstractButton) and w.property("icon_name"):
            set_icon(w, w.property("icon_name"), w.property("icon_token"))
