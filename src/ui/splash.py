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
    c = COLORS["dark"]
    pix = QPixmap(WIDTH, HEIGHT)
    pix.fill(QColor(c["frame"]))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    title_font = QFont("Segoe UI Variable Display")
    title_font.setPixelSize(15)
    title_font.setWeight(QFont.Weight.DemiBold)
    p.setFont(title_font)
    p.setPen(QColor(c["frame_text"]))
    p.drawText(QRect(0, 34, WIDTH, 118), Qt.AlignmentFlag.AlignCenter, APP_NAME)

    small = QFont("Cascadia Mono")
    small.setPixelSize(11)
    p.setFont(small)
    p.setPen(QColor(c["frame_muted"]))
    p.drawText(QRect(0, 172, WIDTH - 14, 34), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
               tr("version", version=__version__))
    p.end()
    return pix


class SplashScreen(QSplashScreen):
    def __init__(self, mode: str = "dark"):
        super().__init__(_render(mode))
        self._color = QColor(COLORS["dark"]["frame_muted"])
        self.show_message(tr("splash_loading"))

    def show_message(self, text: str) -> None:
        self.showMessage(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self._color)
