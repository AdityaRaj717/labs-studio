"""MainWindow: sidebar on the left, lazily built pages in a QStackedWidget."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QWidget

from src import APP_NAME, __version__
from src import config, features, theme
from src.i18n import tr
from src.ui.log_panel import LogPanel
from src.ui.pages.placeholder import PlaceholderPage
from src.ui.sidebar import NAV_ITEMS, NAV_KEYS, Sidebar

log = logging.getLogger(__name__)

PageFactory = Callable[[], QWidget]

# Pages whose settings, rows and output folder belong to the active project; they are
# rebuilt when the project changes (Phase 12).
PROJECT_PAGES = ("flow_image", "flow_video", "grok", "openai_image", "demo", "upscaler", "video_cut")


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 600)

        self.sidebar = Sidebar(collapsed=bool(config.get("sidebar_collapsed", False)))
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.page_factories: dict[str, PageFactory] = self._default_factories()
        self.current_key: str | None = None
        self.projects = None  # ProjectStore once attach_projects() ran

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.sidebar.page_requested.connect(self.switch_page)
        self.sidebar.theme_toggled.connect(self.toggle_theme)
        self.sidebar.collapsed_changed.connect(lambda c: config.set("sidebar_collapsed", c))
        self.sidebar.version_clicked.connect(self.show_about)

        self._restore_geometry()
        self.switch_page(next((k for k in NAV_KEYS if features.page_shown(k)), NAV_KEYS[0]))

    # ---- page router -------------------------------------------------
    def _default_factories(self) -> dict[str, PageFactory]:
        factories: dict[str, PageFactory] = {}
        for key, label_key, _ in NAV_ITEMS:
            factories[key] = lambda lk=label_key: PlaceholderPage(tr(lk))
        factories["log"] = LogPanel
        return factories

    def register_page(self, key: str, factory: PageFactory) -> None:
        """Later phases call this to swap a placeholder for a real page."""
        self.page_factories[key] = factory
        old = self.pages.pop(key, None)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
            if self.current_key == key:
                self.switch_page(key)

    def page(self, key: str) -> QWidget:
        """Return the page for ``key``, building and caching it on first use."""
        widget = self.pages.get(key)
        if widget is None:
            factory = self.page_factories[key]
            widget = factory()
            self.pages[key] = widget
            self.stack.addWidget(widget)
            log.debug("Built page %s", key)
        return widget

    def switch_page(self, key: str) -> None:
        if key not in self.page_factories:
            log.warning("Unknown page %r", key)
            return
        self.stack.setCurrentWidget(self.page(key))
        self.sidebar.set_current(key)
        if key != self.current_key:
            log.info("Page: %s", key)
        self.current_key = key

    # ---- projects (Phase 12) -----------------------------------------
    def attach_projects(self, store) -> None:
        from src.ui.projects.picker import ProjectPicker

        self.projects = store
        store.busy_check = self.is_busy
        store.listeners.append(self._on_project_event)
        self.picker = ProjectPicker(store, self)
        self.sidebar.set_project_widget(self.picker)
        self._update_title()

    def is_busy(self) -> bool:
        """True while any page runs a batch (generator/tool queue or a workflow)."""
        for page in list(self.pages.values()):
            for w in (page, *page.findChildren(QWidget)):
                queue = getattr(w, "queue", None)
                if queue is not None and callable(getattr(queue, "is_running", None)) and queue.is_running():
                    return True
                running = getattr(w, "is_running", None)
                if callable(running) and not isinstance(w, QStackedWidget) and running():
                    return True
        return False

    def _on_project_event(self, event: str, project) -> None:
        if event == "switched":
            self.reload_project_pages()
        self._update_title()

    def reload_project_pages(self) -> None:
        """Drop the project-scoped pages; they are rebuilt from the new project on next view."""
        for key in PROJECT_PAGES:
            old = self.pages.pop(key, None)
            if old is None:
                continue
            shutdown = getattr(old, "shutdown", None)
            if callable(shutdown):
                shutdown()
            self.stack.removeWidget(old)
            old.deleteLater()
        if self.current_key in PROJECT_PAGES:
            self.switch_page(self.current_key)

    def _update_title(self) -> None:
        active = self.projects.active if self.projects is not None else None
        self.setWindowTitle(f"{APP_NAME} — {active.name}" if active is not None else APP_NAME)

    # ---- theme -------------------------------------------------------
    def toggle_theme(self) -> None:
        new_mode = "light" if theme.current_mode() == "dark" else "dark"
        theme.apply_theme(QApplication.instance(), new_mode)
        config.set("theme", new_mode)
        self.sidebar.update_theme_button()
        self.sidebar.update()
        log.info("Theme: %s", new_mode)

    # ---- misc --------------------------------------------------------
    def show_about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b><br>{tr('version', version=__version__)}")

    def _restore_geometry(self) -> None:
        geometry = config.get("window.geometry")
        if geometry:
            try:
                if self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii"))):
                    return
            except (AttributeError, ValueError):
                pass
        self.resize(1280, 800)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        config.set("window.geometry", geometry)
        for page in self.pages.values():
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                shutdown()
        log.info("Window closed; settings saved")
        super().closeEvent(event)
