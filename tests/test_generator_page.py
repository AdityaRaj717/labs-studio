"""GeneratorPage end to end (offscreen): fake batch with live row status."""

from __future__ import annotations

import time

from openpyxl import Workbook
from PySide6.QtCore import Qt

from src.config import Settings
from src.gen.fake_provider import FakeProvider
from src.gen.models import JobStatus
from src.ui.generator.config_panel import ConfigPanel, COMMON_FIELDS
from src.ui.generator.page import GeneratorPage
from src.ui.generator.prompt_model import COL_OUTPUT, COL_STATUS


def make_page(tmp_path, **provider_kw):
    store = Settings(tmp_path / "settings.json")
    store.set("pages.test_page.save_dir", str(tmp_path / "out"))
    store.set("pages.test_page.delay_min", 0.0)
    store.set("pages.test_page.delay_max", 0.0)
    store.set("pages.test_page.subdir_mode", "batch")
    provider = FakeProvider(**({"step_seconds": 0.01, "steps": 4} | provider_kw))
    return GeneratorPage("test_page", provider, store=store), store


def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_fake_batch_updates_rows(qapp, tmp_path):
    page, _ = make_page(tmp_path)
    page.add_prompts(["a red fox", "a [fail] owl", "a blue whale"])
    seen = set()
    page.model.dataChanged.connect(
        lambda tl, br: seen.add(page.model.data(page.model.index(tl.row(), COL_STATUS))))

    assert page.start() == 3
    assert page.btn_stop.isEnabled() and not page.btn_clear.isEnabled()
    assert run_until(qapp, lambda: not page.queue.is_running() and page.stats_header.stats.get("done") == 2)

    assert [j.status for j in page.jobs] == [JobStatus.DONE, JobStatus.FAILED, JobStatus.DONE]
    assert {"Running", "Done", "Failed"} <= seen
    assert page.jobs[0].outputs[0].parent.parent == tmp_path / "out"
    assert page.model.data(page.model.index(0, COL_OUTPUT), Qt.ItemDataRole.DecorationRole) is not None
    assert "Done 2" in page.stats_header.text() and "Failed 1" in page.stats_header.text()
    assert page.btn_retry.isEnabled() and page.btn_clear.isEnabled()

    # Retry failed: the [fail] row fails again, others untouched.
    assert page.retry_failed() == 1
    assert run_until(qapp, lambda: not page.queue.is_running())
    assert page.jobs[1].status is JobStatus.FAILED and page.jobs[0].status is JobStatus.DONE
    page.shutdown()


def test_stop_then_retry(qapp, tmp_path):
    page, _ = make_page(tmp_path, step_seconds=0.05, steps=10)
    page.config_panel.set_value("threads", 1)
    page.add_prompts([f"p{i}" for i in range(4)])
    page.start()
    assert run_until(qapp, lambda: page.jobs[0].status is JobStatus.RUNNING)
    page.stop()
    assert run_until(qapp, lambda: not page.queue.is_running())
    assert all(j.status is JobStatus.STOPPED for j in page.jobs)
    page.provider.step_seconds = 0
    assert page.retry_failed() == 4
    assert run_until(qapp, lambda: all(j.status is JobStatus.DONE for j in page.jobs))


def test_import_and_ref_match(qapp, tmp_path):
    page, _ = make_page(tmp_path)
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "fox.png").write_bytes(b"x")
    page.config_panel.set_value("ref_dir", str(refs))
    txt = tmp_path / "p.txt"
    txt.write_text("a fox\na cat\n", encoding="utf-8")
    wb = Workbook()
    wb.active.append(["prompt"])
    wb.active.append(["another fox"])
    xlsx = tmp_path / "p.xlsx"
    wb.save(xlsx)

    assert page.import_files([txt, xlsx]) == 3
    assert [j.index for j in page.jobs] == [1, 2, 3]
    assert [len(j.refs) for j in page.jobs] == [1, 0, 1]
    page.remove_rows([0])
    assert [j.prompt for j in page.jobs] == ["a cat", "another fox"]
    assert [j.index for j in page.jobs] == [1, 2]
    page.clear()
    assert page.jobs == [] and page.stats_header.stats["total"] == 0


def test_config_panel_persists(qapp, tmp_path):
    path = tmp_path / "s.json"
    panel = ConfigPanel("pg", FakeProvider().config_fields() + COMMON_FIELDS, Settings(path))
    assert panel.value("threads") == 2 and panel.value("aspect") == "1:1"
    panel.set_value("threads", 5)
    panel.set_value("aspect", "16:9")
    again = ConfigPanel("pg", COMMON_FIELDS + FakeProvider().config_fields(), Settings(path))
    assert again.value("threads") == 5 and again.value("aspect") == "16:9"
    assert again.editors["threads"].value() == 5


def test_main_window_registers_generator_page(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("flow_image")
    assert isinstance(window.page("flow_image"), GeneratorPage)
    window.close()
