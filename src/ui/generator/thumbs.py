"""Thumbnails decoded off the UI thread: paint asks, a pool decodes, ``ready(path)`` repaints.

Workers make ``QImage`` only; the ``QPixmap`` is made on the GUI thread when the result arrives.
Widths come in 80 px buckets, so a slider drag draws the nearest held size scaled until the new
bucket lands. Entries are keyed by path, mtime, bucket and device ratio; the file is stat'ed once
per load and again only by ``refresh`` (a job update), so a regenerated file replaces its thumb.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

BUCKET = 80
CAP_BYTES = 256 * 1024 * 1024


def _read(path: str, w: int, h: int, ratio: float) -> tuple[float | None, QImage | None, tuple[int, int]]:
    """Worker side: mtime, the image scaled to fit ``w`` x ``h`` logical px (never up), source size."""
    try:
        stamp = os.stat(path).st_mtime
    except OSError:
        return None, None, (0, 0)
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        scale = min(w * ratio / size.width(), h * ratio / size.height(), 1.0)
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
    image = reader.read()
    if image.isNull():
        return stamp, None, (0, 0)
    if not size.isValid() or size.width() <= 0:
        size = image.size()
    return stamp, image, (size.width(), size.height())


class ThumbService(QObject):
    ready = Signal(str)  # path: a thumb for it arrived, or it is known missing
    _loaded = Signal(object)

    def __init__(self, cap_bytes: int = CAP_BYTES, parent: QObject | None = None):
        super().__init__(parent)
        self.cap_bytes = cap_bytes
        self.bytes = 0
        self.pool = QThreadPool(self)
        self._lru: OrderedDict[tuple, tuple[QPixmap, tuple[int, int]]] = OrderedDict()
        self._by_path: dict[str, set[tuple]] = {}
        self._stamp: dict[str, float] = {}
        self.missing: set[str] = set()
        self._pending: set[tuple] = set()
        self._loaded.connect(self._on_loaded, Qt.ConnectionType.QueuedConnection)

    def get(self, path: Path | str, w: int, h: int, ratio: float = 1.0) -> QPixmap | None:
        """The thumb to draw at ``w`` x ``h`` logical px, or None while it decodes. Never decodes here."""
        p = str(path)
        if p in self.missing or w <= 0 or h <= 0:
            return None
        bw = -(-int(w) // BUCKET) * BUCKET
        rk = round(ratio * 100)
        stamp = self._stamp.get(p)
        key = (p, stamp, bw, rk)
        hit = self._lru.get(key)
        if hit is not None:
            self._lru.move_to_end(key)
        else:
            if key not in self._pending:
                self._pending.add(key)
                bh = max(1, round(h * bw / w))
                self.pool.start(lambda: self._loaded.emit((key, _read(p, bw, bh, ratio))))
            near = [k for k in self._by_path.get(p, ()) if k[1] == stamp]
            if not near:
                return None
            hit = self._lru[min(near, key=lambda k: (k[3] != rk, abs(k[2] - bw)))]
        pix, (ow, oh) = hit
        # the size the old synchronous path drew: fit, never more pixels than the source
        s = min(w * ratio / ow, h * ratio / oh, 1.0)
        target = max(1.0, ow * s / ratio)
        pix.setDevicePixelRatio(pix.width() / target)  # nearest bucket draws scaled to the asked size
        return pix

    def refresh(self, path: Path | str) -> None:
        """A job update: stat again, so a regenerated file misses the old entries and reloads."""
        p = str(path)
        self.missing.discard(p)
        try:
            self._stamp[p] = os.stat(p).st_mtime
        except OSError:
            self._stamp.pop(p, None)

    def wait(self) -> None:
        """Tests and tools: let every queued decode land."""
        self.pool.waitForDone()
        QCoreApplication.processEvents()

    def _on_loaded(self, result) -> None:
        key, (stamp, image, orig) = result
        self._pending.discard(key)
        p = key[0]
        if image is None:  # missing or unreadable: blank until a job update says otherwise
            self.missing.add(p)
            self.ready.emit(p)
            return
        if stamp >= self._stamp.get(p, stamp):
            self._stamp[p] = stamp
        full = (p, stamp, key[2], key[3])
        if full not in self._lru:
            pix = QPixmap.fromImage(image)
            self._lru[full] = (pix, orig)
            self._by_path.setdefault(p, set()).add(full)
            self.bytes += pix.width() * pix.height() * pix.depth() // 8
            while self.bytes > self.cap_bytes and len(self._lru) > 1:
                old, (gone, _) = self._lru.popitem(last=False)
                self.bytes -= gone.width() * gone.height() * gone.depth() // 8
                self._by_path[old[0]].discard(old)
        self.ready.emit(p)


_service: ThumbService | None = None


def service() -> ThumbService:
    global _service
    if _service is None:
        _service = ThumbService()
        app = QCoreApplication.instance()
        if app is not None:  # first asked from a worker: results must still land on the GUI thread
            _service.moveToThread(app.thread())
    return _service
