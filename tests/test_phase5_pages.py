"""OpenAI Image and Grok pages through the real queue (mocked HTTP), plus their key rows."""

from __future__ import annotations

import httpx

from src.config import Settings
from src.gen.grok import GrokProvider
from src.gen.models import JobStatus
from src.gen.openai_image import OpenAIImageProvider
from src.keys import KeyStore
from src.ui.generator.page import GeneratorPage
from src.ui.pages.settings_page import SettingsPage
from test_generator_page import run_until
from test_grok import FakeTime, MP4, images_response as grok_images, video_handler
from test_keys import FakeKeyring
from test_openai_image import images_response as openai_images


def page_for(tmp_path, name, provider, **extra):
    store = Settings(tmp_path / "settings.json")
    for k, v in ({"save_dir": str(tmp_path / "out"), "delay_min": 0.0, "delay_max": 0.0,
                  "max_retries": 0} | extra).items():
        store.set(f"pages.{name}.{k}", v)
    return GeneratorPage(name, provider, store=store)


def run_batch(qapp, page, prompts):
    page.add_prompts(prompts)
    assert page.start() == len(prompts)
    assert run_until(qapp, lambda: not page.queue.is_running()
                     and page.stats_header.stats.get("done", 0) + page.stats_header.stats.get("failed", 0)
                     == len(prompts))


def test_key_rows_for_openai_and_xai(qapp):
    keys = KeyStore(FakeKeyring(), environ={"XAI_API_KEY": "env"})
    page = SettingsPage(keys)
    assert set(page.keys_tab.rows) == {"gemini", "openai", "xai"}
    assert "XAI_API_KEY" in page.keys_tab.rows["xai"].status.text()
    row = page.keys_tab.rows["openai"]
    row.edit.setText("sk-new")
    row.save()
    assert keys.get("openai") == "sk-new"


def test_openai_page_generates(qapp, tmp_path):
    provider = OpenAIImageProvider(key_source=lambda: "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=openai_images())))
    page = page_for(tmp_path, "oai", provider)
    run_batch(qapp, page, ["a red fox", "a blue whale"])
    for job in page.jobs:
        assert job.status is JobStatus.DONE and job.outputs[0].suffix == ".png"
        assert job.outputs[0].exists()
    page.shutdown()


def test_grok_page_images_and_video(qapp, tmp_path):
    provider = GrokProvider(key_source=lambda: "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=grok_images())))
    page = page_for(tmp_path, "grok_i", provider)
    run_batch(qapp, page, ["a red fox"])
    assert page.jobs[0].status is JobStatus.DONE and page.jobs[0].outputs[0].suffix == ".jpg"
    page.shutdown()

    ft = FakeTime()
    provider = GrokProvider(key_source=lambda: "k", transport=httpx.MockTransport(video_handler(1)),
                            sleep=ft.sleep, clock=ft.clock)
    page = page_for(tmp_path, "grok_v", provider, mode="video")
    run_batch(qapp, page, ["a whale jumps"])
    job = page.jobs[0]
    assert job.status is JobStatus.DONE, job.error
    assert job.outputs[0].suffix == ".mp4" and job.outputs[0].read_bytes() == MP4
    page.shutdown()


def test_grok_page_without_key_fails_row(qapp, tmp_path):
    provider = GrokProvider(key_source=lambda: "", transport=httpx.MockTransport(
        lambda r: httpx.Response(500)))
    page = page_for(tmp_path, "grok_nk", provider)
    run_batch(qapp, page, ["x"])
    assert "No xAI API key" in page.jobs[0].error
    page.shutdown()
