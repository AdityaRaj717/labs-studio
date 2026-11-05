"""Always-visible project picker for the sidebar header: a combo plus an actions menu."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMenu, QToolButton, QWidget

from src.i18n import tr
from src.ui import icons
from src.ui.kit import set_icon
from src.projects import ProjectStore
from src.ui.projects import actions


class ProjectPicker(QWidget):
    def __init__(self, store: ProjectStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.combo = QComboBox()
        self.combo.setToolTip(tr("proj_picker_tip"))
        self.combo.activated.connect(self._picked)
        self.menu_btn = QToolButton()
        set_icon(self.menu_btn, "dots-three", "rail_text")  # the rail follows the theme now
        self.menu_btn.setIconSize(icons.ICON_SIZE)
        self.menu_btn.setAccessibleName(tr("proj_actions"))
        self.menu_btn.setToolTip(tr("proj_actions"))
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_btn.setFixedWidth(28)
        menu = QMenu(self)
        menu.addAction(tr("proj_new"), lambda: actions.new_project(self, store))
        menu.addAction(tr("proj_rename"), lambda: actions.rename_project(self, store, store.active.id))
        menu.addAction(tr("proj_duplicate"), lambda: actions.new_project(self, store, settings_from=store.active.id))
        menu.addAction(tr("proj_open_folder"), lambda: actions.open_folder(store, store.active.id))
        menu.addAction(tr("proj_open_flow"), lambda: actions.open_in_flow(self, store, store.active.id))
        menu.addSeparator()
        menu.addAction(tr("proj_delete"), lambda: actions.delete_project(self, store, store.active.id))
        self.menu_btn.setMenu(menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.menu_btn)
        store.listeners.append(lambda *_: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in sorted(self.store.projects.values(), key=lambda p: p.name.lower()):
            self.combo.addItem(p.name, p.id)
        if self.store.active is not None:
            self.combo.setCurrentIndex(self.combo.findData(self.store.active.id))
        self.combo.blockSignals(False)

    def _picked(self, index: int) -> None:
        pid = self.combo.itemData(index)
        if pid and actions.switch(self, self.store, pid) is None:
            self.refresh()  # refused: show the active project again
