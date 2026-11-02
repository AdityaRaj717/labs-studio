"""Settings → API keys tab."""

from __future__ import annotations

import httpx

from src.config import Settings
from src.gen.models import JobStatus
from src.keys import KeyStore
from src.ui.generator.page import GeneratorPage
from src.ui.generator.prompt_model import COL_OUTPUT
from src.ui.pages.settings_page import SettingsPage
from test_generator_page import run_until
from test_keys import FakeKeyring


def test_api_keys_tab_save_and_clear(qapp):
    keys = KeyStore(FakeKeyring(), environ={"GEMINI_API_KEY": "env"})
    page = SettingsPage(keys)
    row = page.keys_tab.rows["gemini"]
    assert "GEMINI_API_KEY" in row.status.text() and not row.btn_clear.isEnabled()
    row.edit.setText("new-key")
    row.save()
    assert keys.get("gemini") == "new-key" and row.edit.text() == ""
    assert "Credential Manager" in row.status.text() and row.btn_clear.isEnabled()
    row.clear()
    assert keys.source("gemini") == "env"
