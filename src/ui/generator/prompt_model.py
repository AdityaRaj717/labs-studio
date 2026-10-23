"""PromptTableModel: one row per Job."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF

from src.gen.models import Job, JobStatus
from src.i18n import tr

COL_INDEX, COL_PROMPT, COL_CHARACTER, COL_SCENE, COL_REFS, COL_STATUS, COL_PROGRESS, COL_OUTPUT = range(8)
COLUMN_KEYS = ("gen_col_index", "gen_col_prompt", "gen_col_character", "gen_col_scene", "gen_col_refs",
               "gen_col_status", "gen_col_progress", "gen_col_output")
THUMB_HEIGHT = 56
VIDEO_EXTS = {".mp4", ".webm", ".mov"}

STATUS_COLORS = {
    JobStatus.PENDING: "#8b919c",
    JobStatus.QUEUED: "#d29922",
    JobStatus.RUNNING: "#4f8cff",
    JobStatus.DONE: "#3fb950",
    JobStatus.FAILED: "#f85149",
    JobStatus.STOPPED: "#8b919c",
}

Index = QModelIndex | QPersistentModelIndex

_video_pix: QPixmap | None = None


def video_placeholder() -> QPixmap:
    """A drawn 16:9 film tile with a play triangle (no decoding of the video)."""
    global _video_pix
    if _video_pix is None:
        h = THUMB_HEIGHT
        w = h * 16 // 9
        pix = QPixmap(w, h)
        pix.fill(QColor("#1f2430"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3a4150"))
        for x in range(4, w, 12):  # sprocket holes
            p.drawRect(x, 3, 6, 4)
            p.drawRect(x, h - 7, 6, 4)
        p.setBrush(QColor("#4f8cff"))
        cx, cy, r = w / 2, h / 2, h / 5
        p.drawPolygon(QPolygonF([QPointF(cx - r * 0.7, cy - r), QPointF(cx - r * 0.7, cy + r),
                                 QPointF(cx + r, cy)]))
        p.end()
        _video_pix = pix
    return _video_pix


class PromptTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: list[Job] = []
        self._rows: dict[int, int] = {}
        self._thumbs: dict[Path, QPixmap] = {}
        self.editable = True
        self.character_name = None  # callable(job) -> str, set by GeneratorPage (Phase 6)
        self.scene_name = None  # callable(job) -> str, set by GeneratorPage (Phase 14b)

    # ---- data access -------------------------------------------------
    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.jobs)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMN_KEYS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(COLUMN_KEYS[section])
        return None

    def flags(self, index: Index):
        base = super().flags(index)
        if index.column() == COL_PROMPT and self.editable:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: Index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job = self.jobs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_INDEX:
                return job.index
            if col == COL_PROMPT:
                return job.prompt
            if col == COL_CHARACTER:
                return self.character_name(job) if self.character_name else ""
            if col == COL_SCENE:
                return self.scene_name(job) if self.scene_name else ""
            if col == COL_REFS:
                return str(len(job.refs)) if job.refs else ""
            if col == COL_STATUS:
                text = tr(f"status_{job.status.value}")
                if job.status is JobStatus.RUNNING and job.attempts > 1:
                    text += f" ({job.attempts})"
                return text
            if col == COL_PROGRESS:
                return int(round(job.progress * 100))
            if col == COL_OUTPUT and len(job.outputs) > 1:
                return f"+{len(job.outputs) - 1}"
            if col == COL_OUTPUT and not job.outputs and job.error:
                return job.error  # failed row: show why, where the image would be
        elif role == Qt.ItemDataRole.EditRole and col == COL_PROMPT:
            return job.prompt
        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_PROMPT:
                return job.prompt
            if col == COL_REFS and job.refs:
                return "\n".join(p.name for p in job.refs)
            if col == COL_CHARACTER and self.character_name:
                return self.character_name(job) or None
            if col == COL_SCENE and self.scene_name:
                return self.scene_name(job) or None
            if col in (COL_STATUS, COL_OUTPUT) and job.error and not job.outputs:
                return job.error
            if col == COL_OUTPUT and job.outputs:
                return "\n".join(str(p) for p in job.outputs)
        elif role == Qt.ItemDataRole.ForegroundRole and col in (COL_STATUS, COL_OUTPUT):
            return QColor(STATUS_COLORS[job.status])
        elif role == Qt.ItemDataRole.DecorationRole and col == COL_OUTPUT and job.outputs:
            return self._thumb(job.outputs[0])
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_INDEX, COL_REFS):
            return Qt.AlignmentFlag.AlignCenter
        return None

    def setData(self, index: Index, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or index.column() != COL_PROMPT:
            return False
        text = str(value).strip()
        if not text:
            return False
        self.jobs[index.row()].prompt = text
        self.dataChanged.emit(index, index)
        return True

    def _thumb(self, path: Path) -> QPixmap | None:
        pix = self._thumbs.get(path)
        if pix is None and path.suffix.lower() in VIDEO_EXTS:
            pix = self._thumbs[path] = video_placeholder()
        if pix is None:
            pix = QPixmap(str(path))
            if pix.isNull():
                return None
            pix = pix.scaledToHeight(THUMB_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            self._thumbs[path] = pix
        return pix

    # ---- mutation ----------------------------------------------------
    def add_prompts(self, prompts: list[str]) -> list[Job]:
        if not prompts:
            return []
        start = len(self.jobs)
        return self.add_jobs([Job(p, index=start + i + 1) for i, p in enumerate(prompts)])

    def add_jobs(self, new: list[Job]) -> list[Job]:
        """Append ready-made jobs (rows restored from a project)."""
        if not new:
            return []
        start = len(self.jobs)
        for i, job in enumerate(new):
            job.index = start + i + 1
        self.beginInsertRows(QModelIndex(), start, start + len(new) - 1)
        self.jobs.extend(new)
        self.endInsertRows()
        self._reindex()
        return new

    def remove_rows(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.jobs[row]
            self.endRemoveRows()
        for n, job in enumerate(self.jobs, 1):
            job.index = n
        self._reindex()
        if self.jobs:
            self.dataChanged.emit(self.index(0, COL_INDEX), self.index(len(self.jobs) - 1, COL_INDEX))

    def clear(self) -> None:
        self.beginResetModel()
        self.jobs.clear()
        self._thumbs.clear()
        self.endResetModel()
        self._reindex()

    def refresh_job(self, job_id: int) -> None:
        row = self._rows.get(job_id)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMN_KEYS) - 1))

    def refresh_all(self) -> None:
        if self.jobs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.jobs) - 1, len(COLUMN_KEYS) - 1))

    def job_at(self, row: int) -> Job:
        return self.jobs[row]

    def _reindex(self) -> None:
        self._rows = {job.id: row for row, job in enumerate(self.jobs)}
