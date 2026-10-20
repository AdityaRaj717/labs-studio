"""Settings → API keys tab, and the Gemini page through the real queue (mocked HTTP)."""

from __future__ import annotations

import httpx

from src.config import Settings
from src.gen.gemini_image import GeminiImageProvider
from src.gen.models import JobStatus
from src.keys import KeyStore
from src.ui.generator.page import GeneratorPage
from src.ui.generator.prompt_model import COL_OUTPUT
from src.ui.pages.settings_page import SettingsPage
from test_gemini_image import image_response
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


def gemini_page(tmp_path, key, handler):
    store = Settings(tmp_path / "settings.json")
    for k, v in {"save_dir": str(tmp_path / "out"), "delay_min": 0.0, "delay_max": 0.0,
                 "max_retries": 0}.items():
        store.set(f"pages.gp.{k}", v)
    provider = GeminiImageProvider(key_source=lambda: key, transport=httpx.MockTransport(handler))
    return GeneratorPage("gp", provider, store=store)


def test_gemini_batch_through_queue(qapp, tmp_path):
    page = gemini_page(tmp_path, "k", lambda r: httpx.Response(200, json=image_response()))
    page.add_prompts(["a red fox", "a blue whale"])
    assert page.start() == 2
    assert run_until(qapp, lambda: not page.queue.is_running() and page.stats_header.stats.get("done") == 2)
    for job in page.jobs:
        assert job.status is JobStatus.DONE and job.progress == 1.0
        assert job.outputs[0].suffix == ".png" and job.outputs[0].exists()
    page.shutdown()


def test_gemini_no_key_shows_error_row(qapp, tmp_path):
    page = gemini_page(tmp_path, "", lambda r: httpx.Response(500))
    page.add_prompts(["a red fox"])
    page.start()
    assert run_until(qapp, lambda: not page.queue.is_running() and page.stats_header.stats.get("failed") == 1)
    assert "No Gemini API key" in page.jobs[0].error
    # The reason is visible in the row (Output cell), not only in a tooltip.
    assert "No Gemini API key" in page.model.data(page.model.index(0, COL_OUTPUT))
    page.shutdown()
