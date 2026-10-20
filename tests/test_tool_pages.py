"""Phase 7 pages offscreen: missing-binary message, a run through the real JobQueue, compare dialog."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage

from src.config import Settings
from src.gen.models import JobStatus
from src.tools.tasks import FrameExtractorProvider, SlicerProvider, UpscaleProvider
from src.ui.tools.compare import CompareDialog
from src.ui.tools.tool_page import COL_OUTPUT
from src.ui.tools.upscaler import UpscalerPage
from src.ui.tools.video_cut import VideoCutPage
from test_generator_page import run_until
from test_tools import FakeRun, probe_json, which_all


def no_bins(name):
    return None


def make_store(tmp_path):
    store = Settings(tmp_path / "settings.json")
    for key in ("video_cut", "frame_extractor", "upscaler"):
        store.set(f"pages.{key}.save_dir", str(tmp_path / "out"))
    return store


def write_image(path, w=8, h=6, color="red"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return path


def test_missing_binaries_disable_start(qapp, tmp_path):
    store = make_store(tmp_path)
    page = VideoCutPage(store, slicer=SlicerProvider(store, which=no_bins),
                        extractor=FrameExtractorProvider(store, which=no_bins))
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    assert page.slicer.add_files([clip, tmp_path / "notes.txt"]) == 1
    assert page.slicer.add_files([clip]) == 0  # no duplicates
    assert not page.slicer.missing_label.isHidden()
    assert "ffmpeg, ffprobe not found" in page.slicer.missing_label.text()
    assert not page.slicer.btn_start.isEnabled() and page.slicer.start() == 0
    page.shutdown()


def test_slicer_page_runs_queue(qapp, tmp_path):
    store = make_store(tmp_path)
    store.set("pages.video_cut.segment_seconds", 4.0)
    run = FakeRun(lines=["out_time_us=1000000"])
    slicer = SlicerProvider(store, run=run, capture=lambda cmd: probe_json(10), which=which_all)
    page = VideoCutPage(store, slicer=slicer,
                        extractor=FrameExtractorProvider(store, which=which_all))
    folder = tmp_path / "clips"
    folder.mkdir()
    for name in ("a.mp4", "b.MOV", "skip.txt"):
        (folder / name).write_bytes(b"x")
    tab = page.slicer
    assert tab.add_files([folder]) == 2 and tab.missing_label.isHidden()
    assert tab.btn_start.isEnabled()
    assert tab.start() == 2
    assert run_until(qapp, lambda: not tab.queue.is_running() and
                     all(j.status is JobStatus.DONE for j in tab.jobs))
    qapp.processEvents()
    assert [len(j.outputs) for j in tab.jobs] == [3, 3]
    assert tab.table.item(0, COL_OUTPUT).text() == "3 files in a_slices"
    assert tab.jobs[1].outputs[0].suffix == ".mov"
    assert not tab.btn_start.isEnabled()  # everything done
    page.shutdown()


def test_option_rows_follow_mode(qapp, tmp_path):
    store = make_store(tmp_path)
    page = VideoCutPage(store, slicer=SlicerProvider(store, which=which_all),
                        extractor=FrameExtractorProvider(store, which=which_all))
    panel = page.slicer.config_panel
    form = panel.layout()
    assert form.isRowVisible(panel.editors["segment_seconds"])
    assert not form.isRowVisible(panel.editors["ranges"])
    panel.set_value("slice_mode", "ranges")
    assert form.isRowVisible(panel.editors["ranges"])
    assert not form.isRowVisible(panel.editors["segment_seconds"])
    assert store.get("pages.video_cut.slice_mode") == "ranges"


def test_failed_row_shows_error_and_can_rerun(qapp, tmp_path):
    store = make_store(tmp_path)
    frames = FrameExtractorProvider(store, run=FakeRun(fail=True), capture=lambda c: probe_json(5),
                                    which=which_all)
    page = VideoCutPage(store, slicer=SlicerProvider(store, which=which_all), extractor=frames)
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    tab = page.frames
    tab.add_files([clip])
    tab.start()
    assert run_until(qapp, lambda: tab.jobs[0].status is JobStatus.FAILED and not tab.queue.is_running())
    qapp.processEvents()
    assert "boom" in tab.table.item(0, COL_OUTPUT).text()
    frames._run = FakeRun(frames=2)
    assert tab.start() == 1
    assert run_until(qapp, lambda: tab.jobs[0].status is JobStatus.DONE)
    page.shutdown()


def test_upscaler_compare(qapp, tmp_path):
    store = make_store(tmp_path)
    src = write_image(tmp_path / "small.png", 8, 6, "red")

    def fake_run(cmd, on_line=None, should_stop=lambda: False, cwd=None):
        out = cmd[cmd.index("-o") + 1]
        write_image(out, 32, 24, "blue")
        return []

    page = UpscalerPage(store, provider=UpscaleProvider(store, run=fake_run, which=which_all))
    page.add_files([src])
    assert not page.btn_compare.isEnabled()
    page.start()
    assert run_until(qapp, lambda: page.jobs[0].status is JobStatus.DONE)
    qapp.processEvents()
    page.table.selectRow(0)
    assert page.btn_compare.isEnabled()
    dlg = page.compare_dialog(0)
    assert isinstance(dlg, CompareDialog)
    assert dlg.view.before.width() == 8 and dlg.view.after.width() == 32
    dlg.slider.setValue(250)
    assert dlg.view.split == 0.25
    dlg.view.resize(400, 300)
    grab = dlg.view.grab().toImage()
    r = dlg.view.image_rect()
    left = grab.pixelColor(int(r.left() + r.width() * 0.1), int(r.center().y()))
    right = grab.pixelColor(int(r.left() + r.width() * 0.9), int(r.center().y()))
    assert left.red() > 200 and right.blue() > 200
    page.shutdown()


def test_tools_settings_tab(qapp, tmp_path):
    from src.ui.tools.settings_tab import ToolsTab

    store = make_store(tmp_path)
    tab = ToolsTab(store)
    row = tab.rows["realesrgan"]
    row.edit.setText(str(tmp_path / "missing.exe"))
    row.save()
    assert store.get("tools.realesrgan_path") == str(tmp_path / "missing.exe")
    exe = tmp_path / "realesrgan-ncnn-vulkan.exe"
    exe.write_bytes(b"")
    row.edit.setText(str(exe))
    row.save()
    assert str(exe) in row.status.text()


def test_main_window_registers_tool_pages(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("video_cut")
    assert isinstance(window.page("video_cut"), VideoCutPage)
    window.switch_page("upscaler")
    assert isinstance(window.page("upscaler"), UpscalerPage)
    window.switch_page("settings")
    assert window.page("settings").tabs.count() >= 2
    window.close()
