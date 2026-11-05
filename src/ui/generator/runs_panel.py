"""RunsPanel: the engine's recent runs (``flow_list_runs``), each with what the ledger says it spent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from src.i18n import tr
from src.ui.kit import set_icon

COLUMNS = ("gen_runs_name", "gen_runs_kind", "gen_runs_done", "gen_runs_credits", "gen_runs_state")
LIVE = ("queued", "submitting", "generating", "downloading", "running")


def run_state(run: dict[str, Any]) -> str:
    """One word from the job counts the engine gave; nothing guessed beyond them."""
    counts = run.get("counts") or {}
    if any(counts.get(s) for s in LIVE):
        return "running"
    if counts.get("failed"):
        return "failed"
    if counts.get("cancelled") and not counts.get("done"):
        return "cancelled"
    return "done" if counts.get("done") == run.get("total") and run.get("total") else "mixed"


def run_row(run: dict[str, Any]) -> list[str]:
    done = (run.get("counts") or {}).get("done", 0)
    return [str(run.get("name") or run.get("run_id") or ""), str(run.get("kind") or "—"),
            tr("gen_runs_n_of_m", n=done, m=run.get("total", 0)),
            str(run["credits"]) if run.get("credits") is not None else "—", tr(f"gen_runs_state_{run_state(run)}")]


def rows_in_run(jobs, run: dict[str, Any]) -> list[int]:
    """The rows whose picture sits in the run's folder: how a run is found on the sheet."""
    folder = run.get("dir")
    if not folder:
        return []
    root = Path(folder).resolve()
    out = []
    for i, job in enumerate(jobs):
        for path in job.outputs:
            try:
                Path(path).resolve().relative_to(root)
            except ValueError:
                continue
            out.append(i)
            break
    return out


class RunsPanel(QWidget):
    refresh_requested = Signal()
    jump_requested = Signal(object)    # the run dict
    folder_requested = Signal(object)  # Path

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.runs: list[dict[str, Any]] = []
        self.note = QLabel(tr("gen_runs_note"))
        self.note.setObjectName("Hint")
        self.note.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([tr(k) for k in COLUMNS])
        self.tree.setAccessibleName(tr("gen_tab_runs"))
        self.tree.itemDoubleClicked.connect(lambda item, _c: self.jump_requested.emit(self._run(item)))
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.btn_refresh = QPushButton(tr("gen_runs_refresh"))
        set_icon(self.btn_refresh, "arrow-clockwise")
        self.btn_refresh.clicked.connect(lambda _c=False: self.refresh_requested.emit())
        self.btn_jump = QPushButton(tr("gen_runs_jump"))
        self.btn_jump.clicked.connect(lambda _c=False: self.jump_requested.emit(self.current()))
        self.btn_folder = QPushButton(tr("gen_open_folder"))
        set_icon(self.btn_folder, "folder-open")
        self.btn_folder.clicked.connect(lambda _c=False: self.folder_requested.emit(Path(self.current()["dir"])))
        buttons = QHBoxLayout()
        for b in (self.btn_refresh, self.btn_jump, self.btn_folder):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(buttons)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.note)
        self._update_buttons()

    def _run(self, item) -> dict[str, Any] | None:
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def current(self) -> dict[str, Any] | None:
        return self._run(self.tree.currentItem())

    def _update_buttons(self) -> None:
        run = self.current()
        self.btn_jump.setEnabled(run is not None)
        self.btn_folder.setEnabled(bool(run and run.get("dir")))

    def show_runs(self, runs: list[dict[str, Any]]) -> None:
        self.runs = runs
        self.tree.clear()
        for run in runs:
            item = QTreeWidgetItem(run_row(run))
            item.setData(0, Qt.ItemDataRole.UserRole, run)
            item.setToolTip(0, str(run.get("run_id") or ""))
            self.tree.addTopLevelItem(item)
        self.note.setText(tr("gen_runs_note") if runs else tr("gen_runs_none"))
        self._update_buttons()

    def show_error(self, message: str) -> None:
        self.tree.clear()
        self.note.setText(message)
        self._update_buttons()
