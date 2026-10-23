"""Collapsible sidebar: nav buttons, theme toggle and version button.

Icons are glyphs from the Segoe MDL2 Assets font that ships with Windows
10/11, so the app bundles no icon images.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src import APP_NAME, __version__
from src import features, theme
from src.i18n import tr

ICON_FONT = "Segoe MDL2 Assets"

# (page key, i18n label key, MDL2 glyph) in sidebar order.
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("flow_image", "nav_img", ""),
    ("flow_video", "nav_video", ""),
    ("grok", "nav_grok", ""),
    ("openai_image", "nav_openai", ""),
    ("meta_vibes", "nav_meta_vibes", ""),
    ("meta_muse", "nav_meta_muse", ""),
    ("google_vids", "nav_google_vids", ""),
    ("google_pics", "nav_google_pics", ""),
    ("projects", "nav_projects", ""),
    ("characters", "nav_characters", ""),
    ("scenes", "nav_scenes", ""),
    ("workflow", "nav_workflow", ""),
    ("video_editor", "nav_video_editor", ""),
    ("upscaler", "nav_upscaler", ""),
    ("video_cut", "nav_video_cut", ""),
    ("webhook", "nav_webhook", ""),
    ("course", "nav_course", ""),
    ("log", "nav_log", ""),
    ("settings", "nav_settings", ""),
]
NAV_KEYS = [key for key, _, _ in NAV_ITEMS]

GLYPH_MENU = ""
GLYPH_SUN = ""
GLYPH_MOON = ""
GLYPH_INFO = ""

EXPANDED_WIDTH = 210
COLLAPSED_WIDTH = 56


class SidebarButton(QPushButton):
    """Flat button that paints an icon glyph plus a label (label hidden when collapsed).

    The stylesheet paints the background (hover/checked); text is drawn here so
    the glyph and label keep a fixed column whether collapsed or not.
    """

    def __init__(self, glyph: str, label: str, checkable: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.glyph = glyph
        self.label = label
        self.collapsed = False
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(label)

    def set_label(self, label: str) -> None:
        self.label = label
        self.setToolTip(label)
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(COLLAPSED_WIDTH - 12, 36)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        colors = theme.COLORS[theme.current_mode()]
        color = QColor(colors["accent"] if self.isChecked() else colors["text"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(color)

        icon_font = QFont(ICON_FONT)
        icon_font.setPixelSize(16)
        p.setFont(icon_font)
        p.drawText(QRect(0, 0, COLLAPSED_WIDTH - 12, self.height()), Qt.AlignmentFlag.AlignCenter, self.glyph)

        if not self.collapsed:
            text_font = QFont(self.font())
            text_font.setBold(self.isChecked())
            p.setFont(text_font)
            p.setPen(QColor(colors["text"]))
            text_rect = QRect(COLLAPSED_WIDTH - 12, 0, self.width() - COLLAPSED_WIDTH + 8, self.height())
            elided = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, text_rect.width())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        p.end()


class Sidebar(QWidget):
    page_requested = Signal(str)
    theme_toggled = Signal()
    collapsed_changed = Signal(bool)
    version_clicked = Signal()

    def __init__(self, collapsed: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.collapsed = collapsed
        self.buttons: dict[str, SidebarButton] = {}

        # Header: collapse toggle + app name
        self.toggle_btn = QPushButton(GLYPH_MENU)
        self.toggle_btn.setObjectName("SidebarToggle")
        self.toggle_btn.setFont(QFont(ICON_FONT, 11))
        self.toggle_btn.setFixedSize(COLLAPSED_WIDTH - 12, 36)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("SidebarTitle")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        header.addWidget(self.toggle_btn)
        header.addWidget(self.title, 1)

        # Nav list (scrolls if the window is short)
        nav = QWidget()
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, label_key, glyph in NAV_ITEMS:
            btn = SidebarButton(glyph, tr(label_key))
            btn.setProperty("nav_key", key)
            btn.clicked.connect(lambda _checked=False, k=key: self.page_requested.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            btn.setVisible(features.page_shown(key))  # Phase 14b: Flow-only mode
            nav_layout.addWidget(btn)
        nav_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(nav)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Footer: theme toggle + version
        self.theme_btn = SidebarButton(GLYPH_SUN, tr("theme_light"), checkable=False)
        self.theme_btn.setObjectName("SidebarFooterButton")
        self.theme_btn.clicked.connect(self.theme_toggled.emit)
        self.version_btn = SidebarButton(GLYPH_INFO, f"v{__version__}", checkable=False)
        self.version_btn.setObjectName("SidebarFooterButton")
        self.version_btn.setToolTip(tr("version", version=__version__))
        self.version_btn.clicked.connect(self.version_clicked.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.theme_btn)
        layout.addWidget(self.version_btn)

        self.update_theme_button()
        self._apply_collapsed()

    def set_project_widget(self, widget: QWidget) -> None:
        """Show the project picker under the header (hidden while collapsed)."""
        self.project_widget = widget
        self.layout().insertWidget(1, widget)
        widget.setVisible(not self.collapsed)

    def set_current(self, key: str) -> None:
        btn = self.buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        self._apply_collapsed()
        self.collapsed_changed.emit(collapsed)

    def _apply_collapsed(self) -> None:
        self.setFixedWidth(COLLAPSED_WIDTH if self.collapsed else EXPANDED_WIDTH)
        self.title.setVisible(not self.collapsed)
        if getattr(self, "project_widget", None) is not None:
            self.project_widget.setVisible(not self.collapsed)
        self.toggle_btn.setToolTip(tr("sidebar_expand") if self.collapsed else tr("sidebar_collapse"))
        for btn in (*self.buttons.values(), self.theme_btn, self.version_btn):
            btn.set_collapsed(self.collapsed)

    def update_theme_button(self) -> None:
        """Show the action the button will take: sun → go light, moon → go dark."""
        dark = theme.current_mode() == "dark"
        self.theme_btn.glyph = GLYPH_SUN if dark else GLYPH_MOON
        self.theme_btn.set_label(tr("theme_light") if dark else tr("theme_dark"))

    def retranslate(self) -> None:
        for key, label_key, _ in NAV_ITEMS:
            self.buttons[key].set_label(tr(label_key))
        self.update_theme_button()
        self._apply_collapsed()
