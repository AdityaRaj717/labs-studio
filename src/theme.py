"""Dark/light colour tokens and the app-wide Qt stylesheet built from them.

The world is a contact sheet. Pictures sit in black frames on neutral grey, so their colours
can be judged; red is the china marker that decides, amber means something is live now.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

TOKEN_NAMES = (
    "bg", "panel", "sidebar", "text", "text_muted", "accent", "accent_text",
    "border", "hover", "selected", "input_bg", "scrollbar",
    "raised", "border_strong", "marker", "live", "failed", "done", "frame", "frame_text", "frame_muted",
    "rail_text", "rail_muted", "rail_hover", "rail_selected", "rail_border",
)

COLORS: dict[str, dict[str, str]] = {
    "dark": {  # the sheet on a dark bench
        "bg": "#141414",
        "panel": "#1a1a1a",
        "sidebar": "#080808",
        "text": "#ece9e2",
        "text_muted": "#a09d96",
        "accent": "#d92d17",
        "accent_text": "#ffffff",
        "border": "#2c2c2c",
        "hover": "#242424",
        "selected": "#2e2e2e",
        "input_bg": "#101010",
        "scrollbar": "#3d3d3d",
        "raised": "#212121",
        "border_strong": "#4a4a4a",
        "marker": "#ff4a30",
        "live": "#f5a524",
        "failed": "#ff7a9c",
        "done": "#ece9e2",
        "frame": "#000000",
        "frame_text": "#ece9e2",
        "frame_muted": "#9b9890",
        "rail_text": "#ece9e2",
        "rail_muted": "#94918a",
        "rail_hover": "#1a1a1a",
        "rail_selected": "#262626",
        "rail_border": "#232323",
    },
    "light": {  # the sheet on a light table
        "bg": "#efefed",
        "panel": "#f8f8f6",
        "sidebar": "#080808",
        "text": "#161616",
        "text_muted": "#5a5955",
        "accent": "#c7240f",
        "accent_text": "#ffffff",
        "border": "#d3d3cf",
        "hover": "#e3e3e0",
        "selected": "#d9d9d5",
        "input_bg": "#ffffff",
        "scrollbar": "#b4b4b0",
        "raised": "#ffffff",
        "border_strong": "#8e8e8a",
        "marker": "#c7240f",
        "live": "#a65f00",
        "failed": "#b5124f",
        "done": "#161616",
        "frame": "#000000",
        "frame_text": "#ece9e2",
        "frame_muted": "#9b9890",
        "rail_text": "#ece9e2",
        "rail_muted": "#94918a",
        "rail_hover": "#1a1a1a",
        "rail_selected": "#262626",
        "rail_border": "#232323",
    },
}

MODES = tuple(COLORS)

# Three sizes only; rank comes from weight and case.
UI_FONT = '"Segoe UI Variable Text", "Segoe UI"'
TITLE_FONT = '"Bahnschrift SemiBold SemiCondensed", "Bahnschrift", "Segoe UI"'
DATA_FONT = '"Cascadia Mono", Consolas'

_current_mode = "dark"


def current_mode() -> str:
    return _current_mode


def tokens() -> dict[str, str]:
    return COLORS[_current_mode]


def motion_enabled() -> bool:
    """False when Windows is set to show no animations."""
    if sys.platform != "win32":
        return True
    enabled = ctypes.c_int(1)
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)  # SPI_GETCLIENTAREAANIMATION
    except (AttributeError, OSError):
        return True
    return bool(enabled.value)


def apply_theme(app, mode: str) -> str:
    """Restyle the whole QApplication live. Returns the mode actually applied."""
    global _current_mode
    if mode not in COLORS:
        mode = "dark"
    _current_mode = mode
    _apply_platform(app, mode)
    app.setStyleSheet(build_qss(mode, _control_images(mode)))
    return mode


def _apply_platform(app, mode: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")  # the same controls on every Windows version
    # The title bar follows this, so it is dark on the dark sheet.
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light)
    c = COLORS[mode]
    pal = QPalette()
    for role, name in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                       (QPalette.ColorRole.Base, "input_bg"), (QPalette.ColorRole.AlternateBase, "panel"),
                       (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "raised"),
                       (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "raised"),
                       (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                       (QPalette.ColorRole.HighlightedText, "accent_text"), (QPalette.ColorRole.Link, "marker"),
                       (QPalette.ColorRole.LinkVisited, "marker"), (QPalette.ColorRole.PlaceholderText, "text_muted")):
        pal.setColor(role, QColor(c[name]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["text_muted"]))
    app.setPalette(pal)


def _control_images(mode: str) -> dict[str, str]:
    """Tinted arrows and ticks as files, because QSS can only load images by path."""
    from src.ui.icon_data import ICONS

    c = COLORS[mode]
    folder = Path(tempfile.gettempdir()) / "labs-studio-qss" / mode
    out: dict[str, str] = {}
    for key, icon, color in (("down", "caret-down", c["text_muted"]), ("up", "caret-up", c["text_muted"]),
                             ("rail_down", "caret-down", c["rail_muted"]), ("check", "check", c["accent_text"])):
        path = folder / f"{key}.svg"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="{color}">'
                            f'{ICONS[icon]}</svg>', encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write control image: %s", exc)
        out[key] = path.as_posix()
    return out


def build_qss(mode: str, images: dict[str, str] | None = None) -> str:
    c = COLORS.get(mode, COLORS["dark"])
    img = images or {"down": "", "up": "", "rail_down": "", "check": ""}
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: {UI_FONT};
    font-size: 13px;
}}
QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}
QMainWindow, QStackedWidget {{ background-color: {c['bg']}; }}
*:disabled {{ color: {c['text_muted']}; }}

/* ---- rail: dark in both modes, like the sheet's own rebate ---- */
#Sidebar {{ background-color: {c['sidebar']}; }}
#Sidebar QWidget {{ background-color: transparent; color: {c['rail_text']}; }}
#SidebarTitle {{
    font-family: {TITLE_FONT};
    font-size: 20px;
    letter-spacing: 0.2px;
    padding: 0 2px;
}}
QPushButton#NavButton, QPushButton#SidebarFooterButton, QPushButton#SidebarToggle {{
    background-color: transparent;
    border: none;
    border-radius: 2px;
    padding: 0;
    color: {c['rail_text']};
}}
QPushButton#NavButton:hover, QPushButton#SidebarFooterButton:hover, QPushButton#SidebarToggle:hover {{
    background-color: {c['rail_hover']};
}}
QPushButton#NavButton:checked {{ background-color: {c['rail_selected']}; }}
QPushButton#NavButton:focus, QPushButton#SidebarFooterButton:focus, QPushButton#SidebarToggle:focus {{
    background-color: {c['rail_selected']};
}}
#Sidebar QComboBox {{
    background-color: {c['rail_hover']};
    border: 1px solid {c['rail_border']};
    color: {c['rail_text']};
    selection-background-color: {c['rail_selected']};
}}
#Sidebar QComboBox:hover {{ border-color: {c['rail_muted']}; }}
#Sidebar QComboBox::down-arrow {{ image: url({img['rail_down']}); width: 12px; height: 12px; }}
#Sidebar QComboBox QAbstractItemView {{
    background-color: {c['rail_hover']};
    color: {c['rail_text']};
    selection-background-color: {c['rail_selected']};
    selection-color: {c['rail_text']};
    border: 1px solid {c['rail_border']};
}}
#Sidebar QToolButton {{ border: 1px solid {c['rail_border']}; border-radius: 2px; padding: 0; }}
#Sidebar QToolButton:hover {{ background-color: {c['rail_hover']}; border-color: {c['rail_muted']}; }}
#Sidebar QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---- type ---- */
#PageTitle {{ font-family: {TITLE_FONT}; font-size: 20px; }}
#PageBody, #DemoBanner, #StatsNote {{ color: {c['text_muted']}; }}
#RunNotice {{ color: {c['text_muted']}; font-weight: 600; }}
#RunNotice[live="true"] {{ color: {c['live']}; }}
#CreditMeter {{ color: {c['text']}; font-family: {DATA_FONT}; font-size: 11px; }}
#CreditMeter[stale="true"] {{ color: {c['text_muted']}; }}
#FieldHeading {{ font-weight: 600; }}
#Hint {{ color: {c['text_muted']}; }}
#EmptyTitle {{ font-family: {TITLE_FONT}; font-size: 20px; }}
QLabel#StatsHeader {{ color: {c['text_muted']}; font-family: {DATA_FONT}; font-size: 11px; }}
a {{ color: {c['marker']}; }}

/* ---- buttons ---- */
QPushButton, QToolButton {{
    background-color: {c['raised']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    padding: 5px 11px;
    min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ background-color: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {c['selected']}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {c['text']}; }}
QPushButton:disabled, QToolButton:disabled {{
    background-color: transparent;
    color: {c['text_muted']};
    border-color: {c['border']};
}}
QPushButton:checked, QToolButton:checked {{ background-color: {c['selected']}; border-color: {c['border_strong']}; }}
QPushButton#PrimaryButton {{
    background-color: {c['accent']};
    color: {c['accent_text']};
    border-color: {c['accent']};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background-color: {c['marker']}; border-color: {c['marker']}; }}
QPushButton#PrimaryButton:focus {{ border-color: {c['text']}; }}
QPushButton#PrimaryButton:disabled {{
    background-color: transparent;
    color: {c['text_muted']};
    border-color: {c['border']};
    font-weight: 400;
}}
QToolButton#IconButton {{ background-color: transparent; border-color: transparent; padding: 4px; }}
QToolButton#IconButton:hover {{ background-color: {c['hover']}; }}
QToolButton#IconButton:focus {{ border-color: {c['border_strong']}; }}
QToolButton#IconButton:checked {{ background-color: {c['selected']}; }}
QToolButton#Segment {{
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: {c['text_muted']};
    padding: 4px 8px;
}}
QToolButton#Segment:hover {{ color: {c['text']}; }}
QToolButton#Segment:focus {{ color: {c['text']}; background-color: {c['hover']}; }}
QToolButton#Segment:checked {{ color: {c['text']}; border-bottom-color: {c['text']}; font-weight: 600; }}
QPushButton#HelpButton {{ background-color: transparent; border-color: transparent; padding: 0; }}
QPushButton#HelpButton:hover {{ background-color: {c['hover']}; }}

/* ---- fields ---- */
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ padding: 4px 7px; min-height: 18px; }}
QPlainTextEdit, QTextEdit {{ padding: 5px 7px; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {c['text']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {c['text_muted']};
    background-color: transparent;
}}
QSpinBox, QDoubleSpinBox {{ max-width: 130px; font-family: {DATA_FONT}; font-size: 12px; }}
QPlainTextEdit#LogView, QPlainTextEdit#CodeView {{ font-family: {DATA_FONT}; font-size: 12px; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url({img['down']}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {c['raised']};
    border: 1px solid {c['border_strong']};
    selection-background-color: {c['selected']};
    selection-color: {c['text']};
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['hover']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({img['up']}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({img['down']}); width: 10px; height: 10px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {c['border_strong']}; border-radius: 2px; background: {c['input_bg']};
}}
QCheckBox::indicator:hover {{ border-color: {c['text']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({img['check']}); }}
QCheckBox:focus {{ color: {c['text']}; font-weight: 600; }}
QSlider::groove:horizontal {{ height: 2px; background: {c['border_strong']}; }}
QSlider::handle:horizontal {{ width: 8px; margin: -7px 0; background: {c['text']}; border-radius: 1px; }}
QSlider {{ background: transparent; }}

/* ---- panels ---- */
#Inspector {{ background-color: {c['panel']}; border-left: 1px solid {c['border']}; }}
#Inspector QTabWidget::tab-bar {{ left: 12px; }}
#Inspector QWidget {{ background-color: {c['panel']}; }}
#Inspector QLabel, #Inspector QCheckBox, #Inspector QToolButton#Segment, #Inspector QToolButton#IconButton {{ background-color: transparent; }}
#Inspector QPushButton, #Inspector QToolButton {{ background-color: {c['raised']}; }}
#Inspector QPushButton:hover, #Inspector QToolButton:hover {{ background-color: {c['hover']}; }}
#Inspector QPushButton:disabled {{ background-color: transparent; }}
#Inspector QPushButton#PrimaryButton {{ background-color: {c['accent']}; }}
#Inspector QPushButton#PrimaryButton:hover {{ background-color: {c['marker']}; }}
#Inspector QPushButton#PrimaryButton:disabled {{ background-color: transparent; }}
#Inspector QLineEdit, #Inspector QComboBox, #Inspector QSpinBox, #Inspector QDoubleSpinBox, #Inspector QPlainTextEdit {{ background-color: {c['input_bg']}; }}
#TakePreview {{ background-color: {c['frame']}; color: {c['frame_muted']}; }}
#Viewer, #Viewer QWidget {{ background-color: {c['frame']}; color: {c['frame_text']}; }}
#Viewer QLabel {{ background-color: transparent; }}
#Viewer QPushButton, #Viewer QToolButton {{ background-color: {c['rail_selected']}; border-color: {c['rail_border']}; color: {c['frame_text']}; }}
#Viewer QPushButton:hover, #Viewer QToolButton:hover {{ background-color: {c['rail_hover']}; border-color: {c['frame_muted']}; }}
#Viewer QPushButton:disabled, #Viewer QToolButton:disabled {{ background-color: transparent; color: {c['frame_muted']}; }}
#Viewer QPushButton#PrimaryButton {{ background-color: {c['accent']}; border-color: {c['accent']}; color: {c['accent_text']}; }}
#Viewer QPushButton#PrimaryButton:disabled {{ background-color: transparent; border-color: {c['rail_border']}; color: {c['frame_muted']}; }}
#ViewerText {{ color: {c['frame_muted']}; font-family: {DATA_FONT}; font-size: 11px; }}
#ViewerPrompt {{ color: {c['frame_text']}; }}
QTextBrowser#HelpView {{ background-color: {c['bg']}; border: none; padding: 0 16px; }}

QGroupBox {{
    border: none;
    border-top: 1px solid {c['border']};
    margin-top: 12px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 0; padding: 0; }}
QGroupBox QWidget {{ font-weight: 400; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {c['border']}; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {c['text_muted']};
    padding: 6px 2px;
    margin-right: 16px;
}}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['text']}; font-weight: 600; }}
QTabBar:focus {{ outline: none; }}

/* ---- lists and tables ---- */
QAbstractItemView {{ outline: none; }}
QListWidget, QListView {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    selection-background-color: {c['selected']};
    selection-color: {c['text']};
}}
QListWidget::item {{ padding: 5px 6px; }}
QListWidget::item:hover {{ background-color: {c['hover']}; }}
QListWidget::item:selected {{ background-color: {c['selected']}; color: {c['text']}; }}
QListView#Sheet {{ border: none; background-color: {c['bg']}; }}
QTableView {{
    background-color: {c['bg']};
    border: none;
    border-top: 1px solid {c['border']};
    gridline-color: transparent;
    selection-background-color: {c['selected']};
    selection-color: {c['text']};
}}
QTableView::item {{ border-bottom: 1px solid {c['border']}; padding: 2px 6px; }}
QTableView::item:selected {{ background-color: {c['selected']}; }}
QHeaderView {{ background-color: {c['bg']}; }}
QHeaderView::section {{
    background-color: {c['bg']};
    color: {c['text_muted']};
    border: none;
    border-bottom: 1px solid {c['border_strong']};
    padding: 5px 6px;
    font-weight: 600;
    text-align: left;
}}
QScrollArea {{ border: none; background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; min-height: 24px; margin: 2px; border-radius: 1px; }}
QScrollBar::handle:vertical:hover {{ background: {c['border_strong']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; min-width: 24px; margin: 2px; border-radius: 1px; }}

QMenu {{ background-color: {c['raised']}; border: 1px solid {c['border_strong']}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 24px 5px 14px; background: transparent; }}
QMenu::item:selected {{ background-color: {c['selected']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['text_muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 0; }}
QToolTip {{
    background-color: {c['raised']};
    color: {c['text']};
    border: 1px solid {c['border_strong']};
    padding: 3px 5px;
}}
#Palette {{ background-color: {c['raised']}; border: 1px solid {c['border_strong']}; }}
#Palette QWidget {{ background-color: {c['raised']}; }}
#Palette QListWidget {{ border: none; }}
#Palette QLineEdit {{ border: none; border-bottom: 1px solid {c['border']}; border-radius: 0; font-size: 13px; padding: 8px 10px; }}
"""
