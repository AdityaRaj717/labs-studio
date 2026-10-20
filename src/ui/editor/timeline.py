"""Multi-track timeline: ruler, track lanes, a subtitle lane and the playhead.

Drag a clip body to move it (onto another lane of the same kind, too), drag an edge to
trim, click the ruler to move the playhead. Edges snap to other clip edges and the
playhead. Track headers toggle mute (audio) / hide (visual) on click.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from src import theme
from src.editor.model import Clip, Cue, Project, Track

RULER_H = 24
LANE_H = 46
SUB_LANE_H = 34
HEADER_W = 120
EDGE_PX = 6
SNAP_PX = 8

CLIP_COLORS = {
    "image": "#3d7be0", "video": "#7a5af0", "audio": "#2fa36b", "text": "#d08a1f",
}


def _fmt(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"


class TimelineWidget(QWidget):
    clipSelected = Signal(object)        # Clip or None
    cueSelected = Signal(object)         # Cue
    playheadMoved = Signal(float)
    aboutToEdit = Signal()               # before a drag changes the project (undo snapshot)
    edited = Signal()                    # after a drag / toggle changed the project
    contextRequested = Signal(object, object, float)  # clip|None, global QPoint, time
    heightChanged = Signal(int)

    def __init__(self, project: Project, parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self.pps = 60.0               # pixels per second
        self.playhead = 0.0
        self.selected: Clip | None = None
        self._drag: dict | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.relayout()

    # ---- geometry ----------------------------------------------------
    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected = None
        self.relayout()

    def relayout(self) -> None:
        h = RULER_H + LANE_H * len(self.project.tracks) + SUB_LANE_H + 4
        w = HEADER_W + int((self.project.duration + 10) * self.pps)
        self.setMinimumSize(max(w, 400), h)
        self.setFixedHeight(h)
        self.heightChanged.emit(h)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def set_zoom(self, pps: float) -> None:
        self.pps = max(5.0, min(600.0, pps))
        self.relayout()

    def x_of(self, t: float) -> float:
        return HEADER_W + t * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, (x - HEADER_W) / self.pps)

    def lane_y(self, index: int) -> int:
        return RULER_H + index * LANE_H

    def sub_lane_y(self) -> int:
        return RULER_H + LANE_H * len(self.project.tracks)

    def lane_at(self, y: float) -> int | None:
        i = int((y - RULER_H) // LANE_H)
        return i if y >= RULER_H and 0 <= i < len(self.project.tracks) else None

    def clip_rect(self, index: int, clip: Clip) -> QRectF:
        y = self.lane_y(index)
        return QRectF(self.x_of(clip.start), y + 4, max(3.0, clip.duration * self.pps), LANE_H - 8)

    def hit(self, pos: QPointF) -> tuple[Track, Clip, str] | None:
        lane = self.lane_at(pos.y())
        if lane is None or pos.x() < HEADER_W:
            return None
        track = self.project.tracks[lane]
        for clip in reversed(track.sorted_clips()):
            r = self.clip_rect(lane, clip)
            if r.adjusted(-2, 0, 2, 0).contains(pos):
                if pos.x() <= r.left() + EDGE_PX:
                    return track, clip, "left"
                if pos.x() >= r.right() - EDGE_PX:
                    return track, clip, "right"
                return track, clip, "body"
        return None

    def set_playhead(self, t: float, emit: bool = True) -> None:
        self.playhead = max(0.0, t)
        self.update()
        if emit:
            self.playheadMoved.emit(self.playhead)

    def select(self, clip: Clip | None) -> None:
        self.selected = clip
        self.update()
        self.clipSelected.emit(clip)

    # ---- snapping ----------------------------------------------------
    def _snap(self, t: float, ignore: Clip) -> float:
        best, best_d = t, SNAP_PX / self.pps
        points = [0.0, self.playhead]
        for tr_ in self.project.tracks:
            for c in tr_.clips:
                if c is not ignore:
                    points += [c.start, c.end]
        for p in points:
            if abs(p - t) < best_d:
                best, best_d = p, abs(p - t)
        return best

    # ---- mouse -------------------------------------------------------
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        if ev.button() == Qt.MouseButton.RightButton:
            h = self.hit(pos)
            if h:
                self.select(h[1])
            self.contextRequested.emit(h[1] if h else None, ev.globalPosition().toPoint(), self.t_of(pos.x()))
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if pos.y() < RULER_H and pos.x() >= HEADER_W:
            self._drag = {"mode": "playhead"}
            self.set_playhead(self.t_of(pos.x()))
            return
        if pos.x() < HEADER_W:
            lane = self.lane_at(pos.y())
            if lane is not None:
                self.aboutToEdit.emit()
                t = self.project.tracks[lane]
                if t.kind == "audio":
                    t.muted = not t.muted
                else:
                    t.hidden = not t.hidden
                self.update()
                self.edited.emit()
            return
        if pos.y() >= self.sub_lane_y():
            t = self.t_of(pos.x())
            for cue in self.project.cues:
                if cue.start <= t < cue.end:
                    self.cueSelected.emit(cue)
                    break
            self.set_playhead(t)
            return
        h = self.hit(pos)
        if not h:
            self.select(None)
            self.set_playhead(self.t_of(pos.x()))
            return
        track, clip, part = h
        self.select(clip)
        self._drag = {"mode": part, "clip": clip, "track": track, "x0": pos.x(),
                      "start": clip.start, "end": clip.end, "edited": False}

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        d = self._drag
        if not d:
            h = self.hit(pos)
            shape = Qt.CursorShape.ArrowCursor
            if h and h[2] in ("left", "right"):
                shape = Qt.CursorShape.SizeHorCursor
            elif h:
                shape = Qt.CursorShape.OpenHandCursor
            self.setCursor(shape)
            return
        if d["mode"] == "playhead":
            self.set_playhead(self.t_of(pos.x()))
            return
        dt = (pos.x() - d["x0"]) / self.pps
        if not d["edited"]:
            if abs(pos.x() - d["x0"]) < 3:
                return
            self.aboutToEdit.emit()
            d["edited"] = True
        clip: Clip = d["clip"]
        if d["mode"] == "body":
            new = d["start"] + dt
            snapped_start = self._snap(new, clip)
            snapped_end = self._snap(new + clip.duration, clip)
            if snapped_start != new:
                new = snapped_start
            elif snapped_end != new + clip.duration:
                new = snapped_end - clip.duration
            Project.move_clip(clip, new)
            # move across lanes of the same kind
            lane = self.lane_at(pos.y())
            if lane is not None:
                target = self.project.tracks[lane]
                src = d["track"]
                same_family = (target.kind == "audio") == (src.kind == "audio")
                if target is not src and same_family:
                    src.clips = [c for c in src.clips if c is not clip]
                    target.clips.append(clip)
                    d["track"] = target
        elif d["mode"] == "left":
            Project.trim_clip(clip, start=self._snap(d["start"] + dt, clip))
        elif d["mode"] == "right":
            Project.trim_clip(clip, end=self._snap(d["end"] + dt, clip))
        self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        d, self._drag = self._drag, None
        if d and d.get("edited"):
            self.relayout()
            self.edited.emit()
            self.clipSelected.emit(self.selected)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
            self.set_zoom(self.pps * factor)
            ev.accept()
        else:
            ev.ignore()

    # ---- painting ----------------------------------------------------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.COLORS[theme.current_mode()]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(c["bg"]))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        visible = self.visibleRegion().boundingRect()

        # ruler
        p.fillRect(QRectF(0, 0, self.width(), RULER_H), QColor(c["panel"]))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if s * self.pps >= 70)
        t = max(0.0, (visible.left() - HEADER_W) // (step * self.pps) * step)
        p.setPen(QColor(c["text_muted"]))
        while self.x_of(t) <= visible.right() + 1:
            x = self.x_of(t)
            p.drawLine(QPointF(x, RULER_H - 7), QPointF(x, RULER_H))
            p.drawText(QPointF(x + 3, RULER_H - 9), _fmt(t))
            t += step

        # lanes
        for i, track in enumerate(self.project.tracks):
            y = self.lane_y(i)
            p.fillRect(QRectF(HEADER_W, y, self.width() - HEADER_W, LANE_H),
                       QColor(c["panel"] if i % 2 else c["bg"]))
            p.setPen(QPen(QColor(c["border"])))
            p.drawLine(QPointF(0, y + LANE_H), QPointF(self.width(), y + LANE_H))
            off = track.muted if track.kind == "audio" else track.hidden
            for clip in track.sorted_clips():
                self._paint_clip(p, self.clip_rect(i, clip), clip, off, c)

        # subtitle lane
        sy = self.sub_lane_y()
        p.fillRect(QRectF(HEADER_W, sy, self.width() - HEADER_W, SUB_LANE_H), QColor(c["panel"]))
        for cue in self.project.cues:
            r = QRectF(self.x_of(cue.start), sy + 4, max(3.0, (cue.end - cue.start) * self.pps), SUB_LANE_H - 8)
            p.setPen(QPen(QColor("#b04fc0").darker(130)))
            p.setBrush(QColor("#b04fc0"))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor("#ffffff"))
            p.drawText(r.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter, cue.text.replace("\n", " "))

        # headers (painted last so they stay on top of clips)
        hx = max(0, visible.left())
        p.fillRect(QRectF(hx, 0, HEADER_W, self.height()), QColor(c["sidebar"]))
        p.setPen(QColor(c["text"]))
        for i, track in enumerate(self.project.tracks):
            y = self.lane_y(i)
            off = track.muted if track.kind == "audio" else track.hidden
            label = track.name + ("  (muted)" if track.kind == "audio" and off else "  (hidden)" if off else "")
            p.setPen(QColor(c["text_muted"] if off else c["text"]))
            p.drawText(QRectF(hx + 8, y, HEADER_W - 12, LANE_H), Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QPen(QColor(c["border"])))
            p.drawLine(QPointF(hx, y + LANE_H), QPointF(hx + HEADER_W, y + LANE_H))
        p.setPen(QColor(c["text"]))
        p.drawText(QRectF(hx + 8, sy, HEADER_W - 12, SUB_LANE_H), Qt.AlignmentFlag.AlignVCenter, "Subtitles")

        # playhead
        x = self.x_of(self.playhead)
        p.setPen(QPen(QColor(c["accent"]), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.end()

    def _paint_clip(self, p: QPainter, r: QRectF, clip: Clip, off: bool, c: dict) -> None:
        col = QColor(CLIP_COLORS.get(clip.kind, "#888888"))
        if off:
            col.setAlpha(90)
        p.setBrush(col)
        sel = clip is self.selected
        p.setPen(QPen(QColor(c["accent_text"] if sel else col.darker(140)), 2 if sel else 1))
        p.drawRoundedRect(r, 4, 4)
        # fades as dark wedges
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        if clip.fade_in > 0:
            w = min(r.width(), clip.fade_in * self.pps)
            p.drawPolygon([r.bottomLeft(), r.topLeft(), QPointF(r.left() + w, r.top())])
        if clip.fade_out > 0:
            w = min(r.width(), clip.fade_out * self.pps)
            p.drawPolygon([r.bottomRight(), r.topRight(), QPointF(r.right() - w, r.top())])
        p.setPen(QColor("#ffffff"))
        label = clip.name + ("  (loop)" if clip.loop else "")
        p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(max(0, r.width() - 10))))


__all__ = ["TimelineWidget", "Cue"]
