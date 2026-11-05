"""Projects page: every project with its last-used date, output count and Flow project."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QWidget,
)

from src import theme
from src.i18n import tr
from src.projects import ProjectStore
from src.ui import icons
from src.ui.kit import flow_row, header_row, intro_label, page_layout
from src.ui.projects import actions

COLUMNS = ("proj_col_name", "proj_col_last_used", "proj_col_outputs", "proj_col_folder", "proj_col_flow")


class ProjectsPage(QWidget):
    def __init__(self, store: ProjectStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        intro = intro_label(tr("proj_intro"))

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(k) for k in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda _item: self._do(actions.switch))
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.btn_switch = self._button("proj_switch", lambda: self._do(actions.switch))
        self.btn_switch.setObjectName("PrimaryButton")
        self.btn_new = self._button("proj_new", lambda: actions.new_project(self, store))
        self.btn_rename = self._button("proj_rename", lambda: self._do(actions.rename_project))
        self.btn_dup = self._button("proj_duplicate", lambda: self._do(
            lambda parent, s, pid: actions.new_project(parent, s, settings_from=pid)))
        self.btn_folder = self._button("proj_open_folder", lambda: self._do(lambda _p, s, pid: actions.open_folder(s, pid)))
        self.btn_out = self._button("proj_output_dir", lambda: self._do(actions.change_output_dir))
        self.btn_flow = self._button("proj_open_flow", lambda: self._do(actions.open_in_flow))
        self.btn_bind = self._button("proj_bind_flow", lambda: self._do(actions.bind_flow))
        self.btn_delete = self._button("proj_delete", lambda: self._do(actions.delete_project))
        self.btn_refresh = self._button("proj_refresh", self.refresh)

        bar = flow_row(self.btn_switch, self.btn_new, self.btn_rename, self.btn_dup, self.btn_folder,
                       self.btn_out, self.btn_flow, self.btn_bind, self.btn_delete, self.btn_refresh)

        self.root_label = QLabel()
        self.root_label.setObjectName("Hint")
        self.root_label.setWordWrap(True)
        self.root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn_root = self._button("proj_change_root", self.change_root)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root_label, 1)
        root_row.addWidget(btn_root)

        layout = page_layout(self)
        layout.addLayout(header_row(tr("nav_projects")))
        layout.addWidget(intro)
        layout.addWidget(bar)
        layout.addWidget(self.table, 1)
        layout.addLayout(root_row)
        store.listeners.append(lambda *_: self.refresh())
        self.refresh()

    def _button(self, key: str, slot) -> QPushButton:
        b = QPushButton(tr(key))
        b.clicked.connect(lambda _checked=False: slot())
        return b

    def selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _do(self, fn) -> None:
        pid = self.selected_id()
        if pid and pid in self.store.projects:
            fn(self, self.store, pid)
        self.refresh()

    def refresh(self) -> None:
        keep = self.selected_id()
        self.table.setRowCount(0)
        for p in self.store.list():
            row = self.table.rowCount()
            self.table.insertRow(row)
            cells = (p.name, p.last_used.replace("T", " "), str(p.output_count()), str(p.output_dir),
                     p.flow_url or tr("proj_flow_none"))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, p.id)
                    if p is self.store.active:
                        item.setIcon(icons.icon("check", theme.tokens()["marker"]))
                        item.setToolTip(tr("proj_active"))
                self.table.setItem(row, col, item)
            if p.id == keep:
                self.table.selectRow(row)
        self.root_label.setText(tr("proj_root", folder=str(self.store.projects_dir)))
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self.selected_id() is not None
        for b in (self.btn_switch, self.btn_rename, self.btn_dup, self.btn_folder, self.btn_out,
                  self.btn_flow, self.btn_bind, self.btn_delete):
            b.setEnabled(has)

    def change_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("proj_change_root"), str(self.store.root))
        if folder:
            self.store.settings.set("projects.data_root", folder)
            QMessageBox.information(self, tr("proj_change_root"), tr("proj_root_restart"))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.refresh()
        super().showEvent(event)
