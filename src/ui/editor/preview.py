"""Approximate preview of the frame at the playhead, drawn with Qt.

Images, overlays, text clips, fades and subtitles are drawn; video clips show a labelled
tile (decoding video frames would need QtMultimedia). The export is the real render.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.editor.model import Clip, Project

_POS_ALIGN = {"bottom": Qt.AlignmentFlag.AlignBottom, "middle": Qt.AlignmentFlag.AlignVCenter,
              "top": Qt.AlignmentFlag.AlignTop}


def clip_alpha(clip: Clip, t: float) -> float:
    a = clip.opacity
    local = t - clip.start
    if clip.fade_in > 0 and local < clip.fade_in:
        a *= max(0.0, local / clip.fade_in)
    if clip.fade_out > 0 and clip.end - t < clip.fade_out:
        a *= max(0.0, (clip.end - t) / clip.fade_out)
    return a


class PreviewWidget(QWidget):
    def __init__(self, project: Project, parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self.time = 0.0
        self._cache: dict[str, QPixmap] = {}
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_project(self, project: Project) -> None:
        self.project = project
        self.update()

    def set_time(self, t: float) -> None:
        self.time = t
        self.update()

    def _pixmap(self, path: str) -> QPixmap:
        pm = self._cache.get(path)
        if pm is None:
            pm = QPixmap(path)
            if not pm.isNull() and max(pm.width(), pm.height()) > 1920:
                pm = pm.scaled(1920, 1920, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[path] = pm
        return pm

    def frame_rect(self) -> QRectF:
        pw, ph = self.project.width, self.project.height
        s = min(self.width() / pw, self.height() / ph)
        w, h = pw * s, ph * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b0c0f"))
        fr = self.frame_rect()
        scale = fr.width() / self.project.width
        p.fillRect(fr, QColor(self.project.background))
        p.setClipRect(fr)
        t = self.time
        for track in self.project.tracks:
            if track.kind == "audio" or track.hidden:
                continue
            for clip in track.sorted_clips():
                if not (clip.start <= t < clip.end):
                    continue
                p.setOpacity(clip_alpha(clip, t))
                if clip.kind == "text":
                    self._draw_text_clip(p, fr, scale, clip)
                elif track.kind == "overlay":
                    self._draw_media(p, self._overlay_rect(fr, clip), clip)
                else:
                    self._draw_media(p, fr, clip, fit=True)
        p.setOpacity(1.0)
        for cue in self.project.cues_at(t):
            self._draw_cue(p, fr, scale, cue.text)
        p.end()

    def _overlay_rect(self, fr: QRectF, clip: Clip) -> QRectF:
        w = fr.width() * clip.scale
        pm = self._pixmap(clip.path) if clip.kind == "image" else None
        aspect = (pm.height() / pm.width()) if pm is not None and not pm.isNull() else 9 / 16
        h = w * aspect
        return QRectF(fr.left() + (fr.width() - w) * clip.x, fr.top() + (fr.height() - h) * clip.y, w, h)

    def _draw_media(self, p: QPainter, area: QRectF, clip: Clip, fit: bool = False) -> None:
        if clip.kind == "image":
            pm = self._pixmap(clip.path)
            if not pm.isNull():
                if fit:
                    s = min(area.width() / pm.width(), area.height() / pm.height())
                    w, h = pm.width() * s, pm.height() * s
                    area = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
                p.drawPixmap(area, pm, QRectF(pm.rect()))
                return
        p.fillRect(area, QColor("#2a2440"))
        p.setPen(QColor("#d8d0ff"))
        p.drawText(area, Qt.AlignmentFlag.AlignCenter, f"▶ {clip.name}")

    def _draw_text_clip(self, p: QPainter, fr: QRectF, scale: float, clip: Clip) -> None:
        f = QFont(self.project.style.font)
        f.setPixelSize(max(6, int(clip.font_size * scale)))
        f.setBold(self.project.style.bold)
        cx, cy = fr.left() + fr.width() * clip.x, fr.top() + fr.height() * clip.y
        box = QRectF(cx - fr.width() / 2, cy - fr.height() / 2, fr.width(), fr.height())
        self._outlined(p, box, Qt.AlignmentFlag.AlignCenter, clip.text, f, QColor(clip.color), scale)

    def _draw_cue(self, p: QPainter, fr: QRectF, scale: float, text: str) -> None:
        s = self.project.style
        f = QFont(s.font)
        f.setPixelSize(max(6, int(s.size * scale)))
        f.setBold(s.bold)
        f.setItalic(s.italic)
        m = s.margin_v * scale
        box = fr.adjusted(40 * scale, m, -40 * scale, -m)
        align = Qt.AlignmentFlag.AlignHCenter | _POS_ALIGN.get(s.position, Qt.AlignmentFlag.AlignBottom)
        if s.box:
            p.setFont(f)
            br = p.fontMetrics().boundingRect(box.toRect(), int(align), text)
            bg = QColor(s.box_color)
            bg.setAlphaF(s.box_opacity)
            p.fillRect(QRectF(br).adjusted(-6 * scale, -3 * scale, 6 * scale, 3 * scale), bg)
        self._outlined(p, box, align, text, f, QColor(s.color), scale)

    def _outlined(self, p: QPainter, box: QRectF, align, text: str, font: QFont, color: QColor,
                  scale: float) -> None:
        s = self.project.style
        p.setFont(font)
        fm = p.fontMetrics()
        lines = text.split("\n")
        lh = fm.height()
        total_h = lh * len(lines)
        if align & Qt.AlignmentFlag.AlignBottom:
            y0 = box.bottom() - total_h
        elif align & Qt.AlignmentFlag.AlignTop:
            y0 = box.top()
        else:
            y0 = box.center().y() - total_h / 2
        path = QPainterPath()
        for i, line in enumerate(lines):
            w = fm.horizontalAdvance(line)
            path.addText(box.center().x() - w / 2, y0 + i * lh + fm.ascent(), font, line)
        if s.outline > 0 and not s.box:
            p.strokePath(path, QPen(QColor(s.outline_color), max(1.0, s.outline * 2 * scale),
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.fillPath(path, color)
