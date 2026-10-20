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
    from src.gen.gemini_image import GeminiImageProvider
    from src.gen.gemini_video import GeminiVideoProvider
    from src.ui.generator.page import GeneratorPage
    from src.ui.pages.settings_page import SettingsPage

    window.register_page("flow_image", lambda: GeneratorPage(
        "flow_image", GeminiImageProvider(), title=tr("nav_img"), banner=tr("gemini_banner")))
    window.register_page("flow_video", lambda: GeneratorPage(
        "flow_video", GeminiVideoProvider(), title=tr("nav_video"), banner=tr("omni_banner")))
    window.register_page("settings", SettingsPage)


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

    window = MainWindow()
    register_pages(window)
    window.show()
    splash.finish(window)
    log.info("Main window ready")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
