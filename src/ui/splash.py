"""Splash screen drawn in code (no bundled image assets)."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

from src import APP_NAME, __version__
from src.i18n import tr
from src.theme import COLORS

WIDTH, HEIGHT = 420, 220


def _render(mode: str) -> QPixmap:
    c = COLORS.get(mode, COLORS["dark"])
    pix = QPixmap(WIDTH, HEIGHT)
    pix.fill(QColor(c["panel"]))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(c["border"]))
    p.drawRect(0, 0, WIDTH - 1, HEIGHT - 1)

    p.setPen(QColor(c["accent"]))
    p.fillRect(QRect(32, 64, 6, 52), QColor(c["accent"]))

    title_font = QFont()
    title_font.setPointSize(22)
    title_font.setBold(True)
    p.setFont(title_font)
    p.setPen(QColor(c["text"]))
    p.drawText(QRect(52, 60, WIDTH - 80, 36), Qt.AlignmentFlag.AlignVCenter, APP_NAME)

    small = QFont()
    small.setPointSize(10)
    p.setFont(small)
    p.setPen(QColor(c["text_muted"]))
    p.drawText(QRect(52, 94, WIDTH - 80, 24), Qt.AlignmentFlag.AlignVCenter, tr("version", version=__version__))
    p.end()
    return pix


class SplashScreen(QSplashScreen):
    def __init__(self, mode: str = "dark"):
        super().__init__(_render(mode))
        self._color = QColor(COLORS.get(mode, COLORS["dark"])["text_muted"])
        self.show_message(tr("splash_loading"))

    def show_message(self, text: str) -> None:
        self.showMessage(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self._color)
