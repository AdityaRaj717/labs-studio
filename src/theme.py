"""Dark/light colour tokens and the app-wide Qt stylesheet built from them.

A grading suite: pictures sit in mid-grey cells on a neutral bench, so their colours can be
judged; the accent is kept for decisions, amber means something is live now.
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
    "header", "cell", "cell_hover", "cell_selected", "faint", "star", "star_empty",
    "label_red", "label_yellow", "label_green", "label_blue", "label_purple",
)

_LABELS = {"label_red": "#d64a3e", "label_yellow": "#d6b23c", "label_green": "#52a35c",
           "label_blue": "#4180d0", "label_purple": "#8c62c8"}

COLORS: dict[str, dict[str, str]] = {
    "dark": {  # a mid-grey bench, so a picture's colours can be judged
        "sidebar": "#1b1b1d", "rail_text": "#dcdcdc", "rail_muted": "#8c8c8c", "rail_hover": "#262628",
        "rail_selected": "#303033", "rail_border": "#141416",
        "header": "#222224", "panel": "#29292b", "raised": "#333336", "bg": "#333333",
        "cell": "#474747", "cell_hover": "#505050", "cell_selected": "#5a5a5a",
        "text": "#e4e4e4", "text_muted": "#9b9b9b", "faint": "#9a9a9a",
        "border": "#19191a", "border_strong": "#4a4a4c", "hover": "#38383b", "selected": "#424245",
        "input_bg": "#1f1f21", "scrollbar": "#4a4a4c",
        "accent": "#e5562b", "accent_text": "#ffffff", "marker": "#e5562b",
        "live": "#f0a417", "failed": "#e46c8c", "done": "#e4e4e4",
        "star": "#e2e2e2", "star_empty": "#5a5a5a",
        "frame": "#3a3a3a", "frame_text": "#e4e4e4", "frame_muted": "#9b9b9b",
        **_LABELS,
    },
    "light": {  # the lights up
        "sidebar": "#d4d4d6", "rail_text": "#1c1c1c", "rail_muted": "#5c5c5c", "rail_hover": "#c8c8ca",
        "rail_selected": "#bdbdc0", "rail_border": "#c2c2c4",
        "header": "#dadadc", "panel": "#e6e6e8", "raised": "#f1f1f2", "bg": "#a9a9a9",
        "cell": "#b9b9b9", "cell_hover": "#c3c3c3", "cell_selected": "#cdcdcd",
        "text": "#161616", "text_muted": "#3f3f3f", "faint": "#555557",
        "border": "#c4c4c6", "border_strong": "#8a8a8c", "hover": "#d0d0d2", "selected": "#c4c4c7",
        "input_bg": "#f6f6f7", "scrollbar": "#9a9a9c",
        "accent": "#c8401a", "accent_text": "#ffffff", "marker": "#c8401a",
        "live": "#7a4a00", "failed": "#b3164f", "done": "#161616",
        "star": "#1c1c1c", "star_empty": "#8c8c8c",
        "frame": "#b9b9b9", "frame_text": "#161616", "frame_muted": "#4f4f4f",
        **_LABELS,
    },
}

MODES = tuple(COLORS)

# Three sizes only; rank comes from weight and case.
UI_FONT = '"Segoe UI Variable Text", "Segoe UI"'
TITLE_FONT = '"Segoe UI Variable Display", "Segoe UI"'
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


def lighten(color: str, amount: float = 0.08) -> str:
    """``color`` moved ``amount`` of the way to white: the primary button's hover."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(v + (255 - v) * amount):02x}" for v in rgb)


def build_qss(mode: str, images: dict[str, str] | None = None) -> str:
    c = COLORS.get(mode, COLORS["dark"])
    img = images or {"down": "", "up": "", "rail_down": "", "check": ""}
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: {UI_FONT};
    font-size: 12px;
}}
QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}
QMainWindow, QStackedWidget {{ background-color: {c['bg']}; }}
*:disabled {{ color: {c['text_muted']}; }}

/* ---- rail ---- */
#Sidebar {{ background-color: {c['sidebar']}; }}
#Sidebar QWidget {{ background-color: transparent; color: {c['rail_text']}; }}
#SidebarTitle {{
    font-family: {TITLE_FONT};
    font-size: 15px;
    font-weight: 600;
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
#PageTitle {{ font-family: {TITLE_FONT}; font-size: 15px; font-weight: 600; }}
#RunBar, #ToolRow {{ background-color: {c['header']}; border-bottom: 1px solid {c['border']}; }}
#RunBar QWidget, #ToolRow QWidget {{ background-color: transparent; }}
#PageBody, #DemoBanner, #StatsNote {{ color: {c['text_muted']}; }}
#RunNotice {{ color: {c['text_muted']}; font-weight: 600; }}
#RunNotice[live="true"] {{ color: {c['live']}; }}
#CreditMeter {{ color: {c['text_muted']}; font-family: {UI_FONT}; font-size: 11px; }}  /* a sentence, not frame data */
#CreditMeter[stale="true"] {{ color: {c['text_muted']}; }}
#FieldHeading {{ font-weight: 600; }}
#Hint {{ color: {c['text_muted']}; }}
#EmptyTitle {{ font-family: {TITLE_FONT}; font-size: 15px; font-weight: 600; }}
QLabel#StatsHeader {{ color: {c['text_muted']}; font-family: {DATA_FONT}; font-size: 11px; }}
a {{ color: {c['marker']}; }}

/* ---- buttons: flat fills, no outlines; the accent is kept for Start ---- */
QPushButton, QToolButton {{
    background-color: {c['raised']};
    border: none;
    border-radius: 2px;
    padding: 0 10px;
    min-height: 26px;
}}
QPushButton:hover, QToolButton:hover {{ background-color: {c['hover']}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {c['selected']}; }}
QPushButton:focus, QToolButton:focus {{ outline: 1px solid {c['text_muted']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {c['faint']}; }}
QPushButton:checked, QToolButton:checked {{ background-color: {c['selected']}; color: {c['text']}; }}
QPushButton#PrimaryButton {{
    background-color: {c['accent']};
    color: {c['accent_text']};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background-color: {lighten(c['accent'])}; }}
QPushButton#PrimaryButton:disabled {{ background-color: {c['raised']}; color: {c['faint']}; font-weight: 400; }}
QToolButton#IconButton {{ background-color: transparent; padding: 4px; min-height: 0; }}
QToolButton#IconButton:hover {{ background-color: {c['hover']}; }}
QToolButton#IconButton:checked {{ background-color: {c['selected']}; }}
QToolButton#Segment {{
    background-color: transparent;
    border: none;
    color: {c['text_muted']};
    padding: 0 8px;
}}
QToolButton#Segment:hover {{ color: {c['text']}; background-color: {c['hover']}; }}
QToolButton#Segment:checked {{ color: {c['text']}; background-color: {c['selected']}; }}
QToolButton#SectionHeader {{
    background-color: {c['header']};
    border-bottom: 1px solid {c['border']};
    border-radius: 0;
    padding: 0;
    min-height: 26px;
}}
QToolButton#SectionHeader:hover {{ background-color: {c['hover']}; }}
#SectionTitle {{ color: {c['text_muted']}; font-size: 11px; font-weight: 600; }}
#RowLabel {{ color: {c['text_muted']}; font-size: 11px; }}
QToolButton#StarButton {{ background: transparent; color: {c['star_empty']}; padding: 0 1px; min-height: 18px; font-size: 12px; }}
QToolButton#StarButton:checked {{ color: {c['star']}; background: transparent; }}
QToolButton#StarButton:hover {{ color: {c['text']}; }}
QToolButton#LabelSwatch {{ padding: 0; min-height: 0; }}
#Inspector QWidget#TakeStrip {{ background-color: transparent; border: none; }}
#Inspector QPushButton#TakeChip {{ background-color: transparent; }}
QPushButton#TakeChip {{
    background-color: transparent;
    color: {c['text_muted']};
    font-family: {DATA_FONT};
    font-size: 11px;
    padding: 0 8px;
    min-width: 0;
}}
QPushButton#TakeChip:hover {{ color: {c['text']}; background-color: {c['hover']}; }}
QPushButton#TakeChip:checked {{ color: {c['text']}; background-color: {c['selected']}; font-weight: 600; }}
QPushButton#HelpButton {{ background-color: transparent; padding: 0; min-height: 0; }}
QPushButton#HelpButton:hover {{ background-color: {c['hover']}; }}

/* ---- fields ---- */
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    selection-background-color: {c['selected']};
    selection-color: {c['text']};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ padding: 4px 7px; min-height: 18px; }}
QPlainTextEdit, QTextEdit {{ padding: 5px 7px; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {c['text_muted']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {c['text_muted']};
    background-color: transparent;
}}
QSpinBox, QDoubleSpinBox {{ max-width: 130px; font-family: {DATA_FONT}; font-size: 11px; }}
QPlainTextEdit#LogView, QPlainTextEdit#CodeView {{ font-family: {DATA_FONT}; font-size: 11px; }}
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
QCheckBox:focus {{ color: {c['text']}; outline: 1px solid {c['text_muted']}; }}
QSlider::groove:horizontal {{ height: 2px; background: {c['border_strong']}; }}
QSlider::handle:horizontal {{ width: 8px; margin: -7px 0; background: {c['text']}; border-radius: 1px; }}
QSlider {{ background: transparent; }}

/* ---- panels ---- */
#Inspector {{ background-color: {c['panel']}; border-left: 1px solid {c['border']}; }}
#Inspector QTabWidget::tab-bar {{ left: 12px; }}
#Inspector QTabBar {{ background-color: {c['header']}; }}
#Inspector QWidget {{ background-color: {c['panel']}; }}
#Inspector QLabel, #Inspector QCheckBox, #Inspector QToolButton#Segment, #Inspector QToolButton#IconButton,
#Inspector QToolButton#StarButton {{ background-color: transparent; }}
#Inspector QPushButton, #Inspector QToolButton {{ background-color: {c['raised']}; }}
#Inspector QPushButton:hover, #Inspector QToolButton:hover {{ background-color: {c['hover']}; }}
#Inspector QToolButton#SectionHeader {{ background-color: {c['header']}; }}
#Inspector QToolButton#SectionHeader:hover {{ background-color: {c['hover']}; }}
#Inspector QPushButton#PrimaryButton {{ background-color: {c['accent']}; }}
#Inspector QPushButton#PrimaryButton:hover {{ background-color: {lighten(c['accent'])}; }}
#Inspector QLineEdit, #Inspector QComboBox, #Inspector QSpinBox, #Inspector QDoubleSpinBox, #Inspector QPlainTextEdit {{ background-color: {c['input_bg']}; }}
#TakePreview {{ background-color: {c['cell']}; color: {c['text_muted']}; }}
#Viewer, #Viewer QWidget {{ background-color: {c['frame']}; color: {c['frame_text']}; }}
#Viewer QLabel {{ background-color: transparent; }}
#Viewer QPushButton, #Viewer QToolButton {{ background-color: {c['rail_selected']}; border-color: {c['rail_border']}; color: {c['frame_text']}; }}
#Viewer QPushButton:hover, #Viewer QToolButton:hover {{ background-color: {c['rail_hover']}; border-color: {c['frame_muted']}; }}
#Viewer QPushButton:disabled, #Viewer QToolButton:disabled {{ background-color: transparent; color: {c['frame_muted']}; }}
#Viewer QPushButton#PrimaryButton {{ background-color: {c['accent']}; color: {c['accent_text']}; }}
#Viewer QPushButton#PrimaryButton:disabled {{ background-color: transparent; color: {c['frame_muted']}; }}
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
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['text']}; }}
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
QHeaderView {{ background-color: {c['header']}; }}
QHeaderView::section {{
    background-color: {c['header']};
    color: {c['text_muted']};
    font-size: 11px;
    border: none;
    border-bottom: 1px solid {c['border']};
    border-right: 1px solid {c['border']};
    padding: 5px 6px;
    text-align: left;
}}
QScrollArea {{ border: none; background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; min-height: 24px; margin: 1px; border-radius: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['border_strong']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; min-width: 24px; margin: 1px; border-radius: 2px; }}

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
#Palette QLineEdit {{ border: none; border-bottom: 1px solid {c['border']}; border-radius: 0; font-size: 12px; padding: 8px 10px; }}
"""
