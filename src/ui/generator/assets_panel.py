"""AssetsPanel: the bound Flow project's assets (``flow_list_assets``), only the grid window Flow shows."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from src.i18n import tr
from src.ui.kit import set_icon


class AssetsPanel(QWidget):
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.window_note = QLabel(tr("gen_assets_window"))
        self.window_note.setObjectName("Hint")
        self.window_note.setWordWrap(True)
        self.note = QLabel(tr("gen_assets_none"))
        self.note.setObjectName("Hint")
        self.note.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([tr("gen_assets_label"), tr("gen_assets_media")])
        self.tree.setAccessibleName(tr("gen_tab_assets"))
        self.btn_refresh = QPushButton(tr("gen_runs_refresh"))
        set_icon(self.btn_refresh, "arrow-clockwise")
        self.btn_refresh.clicked.connect(lambda _c=False: self.refresh_requested.emit())
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_refresh)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(buttons)
        layout.addWidget(self.window_note)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.note)

    def show_assets(self, reply: dict[str, Any]) -> None:
        assets = reply.get("assets") or []
        self.tree.clear()
        for a in assets:
            item = QTreeWidgetItem([str(a.get("label") or "—"), str(a.get("mediaId") or "")])
            item.setToolTip(1, str(a.get("mediaId") or ""))
            self.tree.addTopLevelItem(item)
        # The engine's own words on the window win; ours stand in when it gives none.
        self.window_note.setText(str(reply.get("note") or tr("gen_assets_window")))
        self.note.setText(tr("gen_assets_count", n=len(assets)) if assets else tr("gen_assets_none"))

    def show_error(self, message: str) -> None:
        self.tree.clear()
        self.note.setText(message)
