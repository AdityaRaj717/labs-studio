"""MainWindow: sidebar on the left, lazily built pages in a QStackedWidget."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QPoint, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QKeySequence, QPainter, QRegion, QShortcut
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QWidget

from src import APP_NAME, __version__
from src import config, features, theme
from src.i18n import tr
from src.ui import kit
from src.ui.log_panel import LogPanel
from src.ui.help.button import attach_help_button
from src.ui.help.page import HelpPage
from src.ui.pages.placeholder import PlaceholderPage
from src.ui.palette import CommandPalette
from src.ui.sidebar import NAV_ITEMS, NAV_KEYS, Sidebar

log = logging.getLogger(__name__)

PageFactory = Callable[[], QWidget]

# Pages whose settings, rows and output folder belong to the active project; they are
# rebuilt when the project changes (Phase 12).
PROJECT_PAGES = ("flow_image", "flow_video")

# Page key -> help topic (help/en/<topic>.md) its "?" button opens (Phase 15).
PAGE_TOPICS: dict[str, str] = {
    "flow_image": "flow-image",
    "flow_video": "flow-image",
    "projects": "projects",
    "characters": "characters-and-scenes",
    "scenes": "characters-and-scenes",
    "webhook": "webhook-api",
    "log": "troubleshooting",
    "settings": "google-flow-sign-in",
}


LIGHTS = (("full", 0.0), ("dim", 0.70), ("out", 0.92))  # L walks them; Esc is full again
LIGHTS_MS = 160


class LightsOverlay(QWidget):
    """Black over the whole window but the sheet, like Lightroom's lights out. Never takes a click."""

    def __init__(self, window: "MainWindow", parent: QWidget):
        super().__init__(parent)
        self.window_ = window
        self.alpha = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.hide()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def hole(self) -> QRect:
        """The sheet's viewport in this widget's coordinates, or an empty rect."""
        sheet = getattr(self.window_.pages.get(self.window_.current_key), "sheet", None)
        if sheet is None or not sheet.isVisible():
            return QRect()
        vp = sheet.viewport()
        return QRect(self.mapFromGlobal(vp.mapToGlobal(QPoint(0, 0))), vp.size())

    def set_alpha(self, alpha: float) -> None:
        self.alpha = alpha
        self.setVisible(alpha > 0)
        self.raise_()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(self.hole())))
        p.fillRect(self.rect(), QColor(0, 0, 0, round(255 * self.alpha)))
        p.end()


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

        self.lights = 0  # index into LIGHTS
        self._lights_anim: QVariantAnimation | None = None
        self.lights_overlay = LightsOverlay(self, central)
        QShortcut(QKeySequence("L"), self, self.cycle_lights)
        self._lights_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, lambda: self.set_lights(0))
        self._lights_esc.setEnabled(False)  # only while the lights are down, so Esc keeps its other jobs

        self.palette_ = CommandPalette(self.palette_commands, central)
        QShortcut(QKeySequence("Ctrl+K"), self, self.palette_.open)
        shown = [k for k in NAV_KEYS if features.page_shown(k)]
        for number, key in enumerate(shown[:9], start=1):
            QShortcut(QKeySequence(f"Ctrl+{number}"), self, lambda k=key: self.switch_page(k))
        self.engine_health = None
        self.chip = None
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._update_live)
        self._live_timer.start()

        self._restore_geometry()
        self.switch_page(next((k for k in NAV_KEYS if features.page_shown(k)), NAV_KEYS[0]))

    # ---- page router -------------------------------------------------
    def _default_factories(self) -> dict[str, PageFactory]:
        factories: dict[str, PageFactory] = {}
        for key, label_key, _ in NAV_ITEMS:
            factories[key] = lambda lk=label_key: PlaceholderPage(tr(lk))
        factories["log"] = LogPanel
        factories["help"] = HelpPage
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
            if key in PAGE_TOPICS and not isinstance(widget, PlaceholderPage):
                attach_help_button(widget, PAGE_TOPICS[key], self.open_help)
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
        self._apply_lights(LIGHTS[self.lights][1])

    # ---- lights ------------------------------------------------------
    def cycle_lights(self) -> None:
        self.set_lights((self.lights + 1) % len(LIGHTS))

    def set_lights(self, level: int) -> None:
        """Fade to ``level`` in 160 ms, or at once when Windows asks for no animation."""
        start = self.lights_overlay.alpha
        self.lights = level
        self._lights_esc.setEnabled(level != 0)
        target = LIGHTS[level][1]
        if self._lights_anim is not None:
            self._lights_anim.stop()
            self._lights_anim = None
        if not theme.motion_enabled() or start == target:
            self._apply_lights(target)
            return
        anim = QVariantAnimation(self)
        anim.setDuration(LIGHTS_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(float(start))
        anim.setEndValue(float(target))
        anim.valueChanged.connect(self._apply_lights)
        anim.finished.connect(lambda: setattr(self, "_lights_anim", None))  # deleted when stopped: never touch it after
        self._lights_anim = anim
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _apply_lights(self, alpha: float) -> None:
        self.lights_overlay.set_alpha(alpha)
        for page in self.pages.values():
            sheet = getattr(page, "sheet", None)
            if sheet is not None:
                sheet.set_dim(alpha)

    def _update_live(self) -> None:
        """The rail's amber mark: which page has a batch running, seen from anywhere, agent runs included."""
        health = self.engine_health
        engine_key = None
        if health is not None and health.active:
            engine_key = "flow_video" if health.active_kind == "video" else "flow_image"
        for key in PROJECT_PAGES:
            queue = getattr(self.pages.get(key), "queue", None)
            self.sidebar.set_live(key, key == engine_key or (queue is not None and queue.is_running()))

    def set_engine_health(self, health) -> None:
        """The engine's ``/health`` (an EngineHealth, or None when none was started), from HealthWatch."""
        self.engine_health = health
        if self.chip is not None:
            self.chip.refresh(idle=health is not None and not health.active and not self.is_busy(),
                              running=health is not None and not health.down)
        for key in PROJECT_PAGES:
            show = getattr(self.pages.get(key), "set_engine_health", None)
            if callable(show):
                show(health)
        self._update_live()

    def palette_commands(self) -> list[tuple[str, Callable[[], None]]]:
        """The current page's own actions first, then every page, then the window."""
        commands = []
        own = getattr(self.pages.get(self.current_key), "palette_commands", None)
        if callable(own):
            commands += own()
        for key, label_key, _ in NAV_ITEMS:
            if features.page_shown(key):
                commands.append((tr("palette_go", page=tr(label_key)), lambda k=key: self.switch_page(k)))
        commands.append((tr("palette_toggle_theme"), self.toggle_theme))
        commands.append((tr("palette_toggle_sidebar"), self.sidebar.toggle_collapsed))
        for level, (name, _alpha) in enumerate(LIGHTS):
            commands.append((tr("palette_lights", level=tr(f"lights_{name}")), lambda n=level: self.set_lights(n)))
        if self.projects is not None:
            from src.ui.projects import actions

            commands.append((tr("palette_new_project"), lambda: actions.new_project(self, self.projects)))
        return commands

    def open_help(self, topic: str) -> None:
        """Show the Help page on ``topic`` (the pages' "?" buttons)."""
        self.switch_page("help")
        self.page("help").open_topic(topic)

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
        """True while any page runs a batch."""
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
        kit.repolish_tree()
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
        if getattr(self, "run_mirror", None) is not None:
            self.run_mirror.stop()
        if getattr(self, "health_watch", None) is not None:
            self.health_watch.stop()
        log.info("Window closed; settings saved")
        super().closeEvent(event)
