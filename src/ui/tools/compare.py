"""Before/after compare dialog: drag the divider to wipe between original and upscale."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from src.i18n import tr


def load_pixmap(path: Path) -> QPixmap:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    return QPixmap.fromImage(image)


class CompareView(QWidget):
    """Paints ``after`` with ``before`` (stretched to the same size) left of the split."""

    def __init__(self, before: QPixmap, after: QPixmap, parent: QWidget | None = None):
        super().__init__(parent)
        self.before = before
        self.after = after
        self.split = 0.5
        self.setMinimumSize(320, 240)
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(960, 640)

    def image_rect(self) -> QRectF:
        src = self.after if not self.after.isNull() else self.before
        if src.isNull():
            return QRectF(self.rect())
        size = src.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        return QRectF(x, y, size.width(), size.height())

    def set_split(self, value: float) -> None:
        self.split = max(0.0, min(1.0, value))
        self.update()

    def _split_from_x(self, x: float) -> None:
        r = self.image_rect()
        if r.width() > 0:
            self.set_split((x - r.left()) / r.width())

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._split_from_x(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._split_from_x(event.position().x())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.image_rect()
        cut = r.left() + r.width() * self.split
        if not self.after.isNull():
            p.drawPixmap(r, self.after, QRectF(self.after.rect()))
        if not self.before.isNull():
            p.save()
            p.setClipRect(QRectF(r.left(), r.top(), cut - r.left(), r.height()))
            p.drawPixmap(r, self.before, QRectF(self.before.rect()))
            p.restore()
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(QPointF(cut, r.top()), QPointF(cut, r.bottom()))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cut, r.center().y()), 7, 7)
        p.end()


class CompareDialog(QDialog):
    def __init__(self, before: Path, after: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("up_compare_title", name=Path(before).name))
        b, a = load_pixmap(before), load_pixmap(after)
        self.view = CompareView(b, a)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(500)
        self.slider.valueChanged.connect(lambda v: self.view.set_split(v / 1000))

        def size_text(pix: QPixmap) -> str:
            return f"{pix.width()}×{pix.height()}" if not pix.isNull() else "?"

        left = QLabel(tr("up_before", size=size_text(b)))
        right = QLabel(tr("up_after", size=size_text(a)))
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        labels = QHBoxLayout()
        labels.addWidget(left)
        labels.addStretch(1)
        labels.addWidget(right)

        layout = QVBoxLayout(self)
        layout.addLayout(labels)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.slider)
        self.resize(1000, 720)
