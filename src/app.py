"""Entry point: QApplication → splash → MainWindow."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from src import APP_NAME, __version__
from src import config, theme
from src.config import APP_DIR_NAME
from src.i18n import set_language, tr
from src.ui.log_panel import setup_logging

log = logging.getLogger(__name__)


def register_pages(window) -> None:
    """Swap sidebar placeholders for real pages."""
    from src.ui.generator.page import GeneratorPage
    from src.ui.pages.settings_page import SettingsPage

    from src.gen.web_flow_image import WebFlowImageProvider  # Phase 11a

    window.register_page("flow_image", lambda: GeneratorPage(
        "flow_image", WebFlowImageProvider(), title=tr("nav_img"), banner=tr("web_flow_banner")))
    window.register_page("settings", SettingsPage)

    from src.ui.characters.page import CharactersPage  # Phase 6
    window.register_page("characters", CharactersPage)
    window.register_page("scenes", lambda: CharactersPage(kind="scene"))  # Phase 14b

    if window.projects is not None:  # Phase 12
        from src.ui.projects.page import ProjectsPage
        window.register_page("projects", lambda: ProjectsPage(window.projects))

    from src.ui.webhook.page import WebhookPage  # Phase 10
    window.register_page("webhook", lambda: WebhookPage(window.page, window.switch_page))


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    # No organisation name, so AppDataLocation is %APPDATA%\LabsStudio.
    app.setApplicationName(APP_DIR_NAME)
    app.setOrganizationName("")
    app.setApplicationVersion(__version__)

    data_dir = config.app_data_dir()
    setup_logging(data_dir / "logs")
    log.info("%s %s starting (Python %s)", APP_NAME, __version__, sys.version.split()[0])
    log.info("App data: %s", data_dir)

    settings = config.settings()
    set_language(settings.get("language", "en"))
    mode = theme.apply_theme(app, settings.get("theme", "dark"))
    log.info("Theme: %s, language: %s", mode, settings.get("language"))

    from src.ui.splash import SplashScreen

    splash = SplashScreen(mode)
    splash.show()
    app.processEvents()

    from src.ui.main_window import MainWindow

    from src.stats.store import install as install_stats  # Phase 10
    install_stats()

    from src import projects  # Phase 12: before any page reads pages.* settings
    store = projects.install(settings)

    def open_flow_project(event: str, project) -> None:
        if event == "switched" or (event == "renamed" and project is store.active and project.flow_url):
            if settings.get("web.flow_open_on_switch", True):
                from src.web.flow_mcp import open_project_async
                open_project_async(project)
    store.listeners.append(open_flow_project)

    window = MainWindow()
    window.attach_projects(store)
    register_pages(window)
    if settings.get("webhook.autostart", False):  # Phase 10
        window.page("webhook").start_server()
    window.show()
    splash.finish(window)
    log.info("Main window ready")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
