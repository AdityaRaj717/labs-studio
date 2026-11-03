"""Collapsible sidebar: nav buttons, theme toggle and version button.

The rail stays dark in both modes, like the black rebate around a contact sheet. The current
page gets the china-marker tick; a page with a batch running gets the live dot.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from src import APP_NAME, __version__
from src import features, theme
from src.i18n import tr
from src.ui import icons
from src.ui.kit import IconButton

# (page key, i18n label key, Phosphor icon) in sidebar order.
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("flow_image", "nav_img", "image"),
    ("flow_video", "nav_video", "film-strip"),
    ("projects", "nav_projects", "folders"),
    ("characters", "nav_characters", "users-three"),
    ("scenes", "nav_scenes", "mountains"),
    ("webhook", "nav_webhook", "plugs-connected"),
    ("log", "nav_log", "scroll"),
    ("settings", "nav_settings", "gear-six"),
    ("help", "nav_help", "question"),  # Phase 15
]
NAV_KEYS = [key for key, _, _ in NAV_ITEMS]
GROUP_STARTS = {"projects", "webhook"}  # a gap before each: the desk, the library, the back room

EXPANDED_WIDTH = 196
COLLAPSED_WIDTH = 52
ROW_HEIGHT = 32
ICON_COLUMN = COLLAPSED_WIDTH - 16


class SidebarButton(QPushButton):
    """Flat button that paints an icon plus a label (label hidden when collapsed).

    The stylesheet paints the background (hover/checked); the rest is drawn here so
    the icon and label keep a fixed column whether collapsed or not.
    """

    def __init__(self, glyph: str, label: str, checkable: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.glyph = glyph
        self.label = label
        self.collapsed = False
        self.live = False
        self.setObjectName("NavButton")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(label)
        self.setAccessibleName(label)

    def set_label(self, label: str) -> None:
        self.label = label
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self.update()

    def set_live(self, live: bool) -> None:
        if live != self.live:
            self.live = live
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(ICON_COLUMN, ROW_HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        colors = theme.tokens()
        on = self.isChecked()
        muted = self.objectName() == "SidebarFooterButton"
        ink = colors["rail_muted"] if muted else colors["rail_text"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        ratio = self.devicePixelRatioF()
        x = (ICON_COLUMN - 16) // 2
        p.drawPixmap(x, (self.height() - 16) // 2, icons.pixmap(self.glyph, ink, 16, ratio))

        if not self.collapsed:
            text_font = QFont(self.font())
            text_font.setWeight(QFont.Weight.DemiBold if on else QFont.Weight.Normal)
            p.setFont(text_font)
            p.setPen(QColor(ink))
            text_rect = QRect(ICON_COLUMN, 0, self.width() - ICON_COLUMN - 22, self.height())
            elided = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, text_rect.width())
            p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        if self.live:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.COLORS["dark"]["live"]))
            cx = ICON_COLUMN - 7 if self.collapsed else self.width() - 12
            cy = 9 if self.collapsed else self.height() / 2
            p.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7, 7))
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
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("SidebarToggle")
        self.toggle_btn.setFixedSize(ICON_COLUMN, ROW_HEIGHT)
        self.toggle_btn.setIcon(icons.icon("sidebar-simple", theme.COLORS["dark"]["rail_muted"]))
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("SidebarTitle")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)
        header.addWidget(self.toggle_btn)
        header.addWidget(self.title, 1)

        # Nav list (scrolls if the window is short)
        nav = QWidget()
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(1)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, label_key, glyph in NAV_ITEMS:
            btn = SidebarButton(glyph, tr(label_key))
            btn.setProperty("nav_key", key)
            btn.clicked.connect(lambda _checked=False, k=key: self.page_requested.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            btn.setVisible(features.page_shown(key))  # Phase 14b: Flow-only mode
            if key in GROUP_STARTS:
                nav_layout.addSpacing(14)
            nav_layout.addWidget(btn)
        nav_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(nav)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Footer: theme toggle + version
        self.theme_btn = SidebarButton("sun", tr("theme_light"), checkable=False)
        self.theme_btn.setObjectName("SidebarFooterButton")
        self.theme_btn.clicked.connect(self.theme_toggled.emit)
        self.version_btn = SidebarButton("info", f"v{__version__}", checkable=False)
        self.version_btn.setObjectName("SidebarFooterButton")
        self.version_btn.setToolTip(tr("version", version=__version__))
        self.version_btn.clicked.connect(self.version_clicked.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        footer = QVBoxLayout()
        footer.setSpacing(1)
        footer.addWidget(self.theme_btn)
        footer.addWidget(self.version_btn)
        layout.addLayout(footer)

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

    def set_live(self, key: str, live: bool) -> None:
        btn = self.buttons.get(key)
        if btn is not None:
            btn.set_live(live)

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
        self.toggle_btn.setAccessibleName(self.toggle_btn.toolTip())
        for btn in (*self.buttons.values(), self.theme_btn, self.version_btn):
            btn.set_collapsed(self.collapsed)

    def update_theme_button(self) -> None:
        """Show the action the button will take: sun → go light, moon → go dark."""
        dark = theme.current_mode() == "dark"
        self.theme_btn.glyph = "sun" if dark else "moon"
        self.theme_btn.set_label(tr("theme_light") if dark else tr("theme_dark"))

    def retranslate(self) -> None:
        for key, label_key, _ in NAV_ITEMS:
            self.buttons[key].set_label(tr(label_key))
        self.update_theme_button()
        self._apply_collapsed()
