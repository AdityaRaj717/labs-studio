"""Dark/light colour tokens and the app-wide Qt stylesheet built from them."""

from __future__ import annotations

TOKEN_NAMES = (
    "bg", "panel", "sidebar", "text", "text_muted", "accent", "accent_text",
    "border", "hover", "selected", "input_bg", "scrollbar",
)

COLORS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#16181d",
        "panel": "#1e2128",
        "sidebar": "#121419",
        "text": "#e6e8ec",
        "text_muted": "#8b919c",
        "accent": "#4f8cff",
        "accent_text": "#ffffff",
        "border": "#2b2f38",
        "hover": "#252a33",
        "selected": "#2a3550",
        "input_bg": "#14161b",
        "scrollbar": "#3a3f4a",
    },
    "light": {
        "bg": "#f5f6f8",
        "panel": "#ffffff",
        "sidebar": "#eceef2",
        "text": "#1c1f24",
        "text_muted": "#646b76",
        "accent": "#2f6fe4",
        "accent_text": "#ffffff",
        "border": "#d8dce3",
        "hover": "#e1e5ec",
        "selected": "#d6e2fb",
        "input_bg": "#ffffff",
        "scrollbar": "#c3c8d1",
    },
}

MODES = tuple(COLORS)

_current_mode = "dark"


def current_mode() -> str:
    return _current_mode


def apply_theme(app, mode: str) -> str:
    """Restyle the whole QApplication live. Returns the mode actually applied."""
    global _current_mode
    if mode not in COLORS:
        mode = "dark"
    _current_mode = mode
    app.setStyleSheet(build_qss(mode))
    return mode


def build_qss(mode: str) -> str:
    c = COLORS.get(mode, COLORS["dark"])
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-size: 13px;
}}
QMainWindow, QStackedWidget {{ background-color: {c['bg']}; }}

#Sidebar {{
    background-color: {c['sidebar']};
    border-right: 1px solid {c['border']};
}}
#Sidebar QWidget {{ background-color: transparent; }}
#SidebarTitle {{ font-size: 15px; font-weight: 600; padding: 4px 6px; }}

SidebarButton, #SidebarFooterButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 7px 10px;
    text-align: left;
    color: {c['text']};
}}
SidebarButton:hover, #SidebarFooterButton:hover {{ background-color: {c['hover']}; }}
SidebarButton:checked {{
    background-color: {c['selected']};
    color: {c['text']};
    font-weight: 600;
}}
#SidebarToggle {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px;
}}
#SidebarToggle:hover {{ background-color: {c['hover']}; }}
#SidebarFooterButton {{ color: {c['text_muted']}; }}

#PageTitle {{ font-size: 22px; font-weight: 600; }}
#PageBody {{ color: {c['text_muted']}; }}

QPlainTextEdit, QLineEdit, QTextEdit {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}
QPlainTextEdit#LogView {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}

QPushButton {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background-color: {c['hover']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; border-radius: 4px; min-width: 24px; }}

QToolTip {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}
"""
