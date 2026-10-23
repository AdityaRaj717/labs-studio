"""Settings page: tabs; phase 3 ships the API keys tab."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout,
    QWidget,
)

from src import features
from src.i18n import tr
from src.keys import KeyStore, store as default_store

# (provider id, label key, where to get a key, link text key)
KEY_PROVIDERS = [
    ("gemini", "keys_gemini", "https://aistudio.google.com/apikey", "keys_get_key"),
    ("openai", "keys_openai", "https://platform.openai.com/api-keys", "keys_get_key_openai"),
    ("xai", "keys_xai", "https://console.x.ai/", "keys_get_key_xai"),
]


class KeyRow(QGroupBox):
    def __init__(self, provider: str, label_key: str, url: str, keys: KeyStore,
                 link_key: str = "keys_get_key", parent: QWidget | None = None):
        super().__init__(tr(label_key), parent)
        self.provider = provider
        self.keys = keys

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(tr("keys_placeholder"))
        self.show_box = QCheckBox(tr("keys_show"))
        self.show_box.toggled.connect(self._toggle_echo)
        self.btn_save = QPushButton(tr("keys_save"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self.save)
        self.btn_clear = QPushButton(tr("keys_clear"))
        self.btn_clear.clicked.connect(self.clear)
        self.status = QLabel()
        self.status.setObjectName("PageBody")
        link = QLabel(f'<a href="{url}">{tr(link_key)}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(self.show_box)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_clear)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addWidget(link)
        self.refresh()

    def _toggle_echo(self, on: bool) -> None:
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)

    def refresh(self) -> None:
        source = self.keys.source(self.provider)
        if source == "keyring":
            text = tr("keys_status_keyring")
        elif source == "env":
            text = tr("keys_status_env").format(name=self.keys.env_var(self.provider))
        else:
            text = tr("keys_status_none")
        self.status.setText(text)
        self.btn_clear.setEnabled(source == "keyring")

    def save(self) -> None:
        if not self.edit.text().strip():
            return
        try:
            self.keys.set(self.provider, self.edit.text())
        except Exception as exc:  # noqa: BLE001 - show keyring failures instead of crashing
            self.status.setText(tr("keys_save_failed").format(error=type(exc).__name__))
            return
        self.edit.clear()
        self.refresh()

    def clear(self) -> None:
        self.keys.clear(self.provider)
        self.edit.clear()
        self.refresh()


class ApiKeysTab(QWidget):
    def __init__(self, keys: KeyStore, parent: QWidget | None = None):
        super().__init__(parent)
        intro = QLabel(tr("keys_intro"))
        intro.setWordWrap(True)
        intro.setObjectName("PageBody")
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        self.rows = {p: KeyRow(p, label, url, keys, link)
                     for p, label, url, link in KEY_PROVIDERS}
        for row in self.rows.values():
            layout.addWidget(row)
        layout.addStretch(1)


class SettingsPage(QWidget):
    def __init__(self, keys: KeyStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        title = QLabel(tr("nav_settings"))
        title.setObjectName("PageTitle")
        self.tabs = QTabWidget()
        self.keys_tab = ApiKeysTab(keys or default_store())
        if features.shown("settings:api_keys"):  # Phase 14b: hidden in Flow-only mode
            self.tabs.addTab(self.keys_tab, tr("settings_tab_keys"))
        if features.shown("settings:tools"):
            from src.ui.tools.settings_tab import ToolsTab  # Phase 7
            self.tabs.addTab(ToolsTab(), tr("settings_tab_tools"))
        from src.ui.pages.web_sessions_tab import WebSessionsTab  # Phase 11
        self.web_tab = WebSessionsTab()
        self.tabs.addTab(self.web_tab, tr("settings_tab_web"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(title)
        layout.addWidget(self.tabs, 1)
