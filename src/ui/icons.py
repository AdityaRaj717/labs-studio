"""Tinted Phosphor icons drawn from the SVG paths in icon_data."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src import theme
from src.ui.icon_data import ICONS

_cache: dict[tuple[str, str, int, float], QPixmap] = {}


def pixmap(name: str, color: str, size: int = 16, ratio: float = 1.0) -> QPixmap:
    key = (name, color, size, ratio)
    pix = _cache.get(key)
    if pix is None:
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="{color}">{ICONS[name]}</svg>'
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        px = round(size * ratio)
        pix = QPixmap(px, px)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        renderer.render(p, QRectF(0, 0, px, px))
        p.end()
        pix.setDevicePixelRatio(ratio)
        _cache[key] = pix
    return pix


def icon(name: str, color: str, size: int = 16) -> QIcon:
    out = QIcon()
    for ratio in (1.0, 2.0):
        out.addPixmap(pixmap(name, color, size, ratio))
        out.addPixmap(pixmap(name, theme.tokens()["text_muted"], size, ratio), QIcon.Mode.Disabled)
    return out


ICON_SIZE = QSize(16, 16)
