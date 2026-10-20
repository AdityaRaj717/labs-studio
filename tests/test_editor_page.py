"""Video Editor page smoke tests (offscreen Qt, ffmpeg mocked)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from src.config import Settings
from src.editor import ffmpeg as ff
from src.editor.model import Cue
from src.languages.en import STRINGS as EN


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ff, "find_ffmpeg", lambda configured=None: None)
    from src.ui.editor.page import VideoEditorPage

    p = VideoEditorPage(store=Settings(tmp_path / "settings.json"))
    yield p
    p.shutdown()
    p.deleteLater()


def test_every_editor_key_has_english_text():
    src = Path(__file__).resolve().parents[1] / "src" / "ui" / "editor"
    used = set()
    for f in src.glob("*.py"):
        used |= set(re.findall(r"[\"'](ed_[a-z_]+)[\"']", f.read_text(encoding="utf-8")))
    dynamic = {f"ed_{p}_{s}" for p, ss in {"f": ["start", "duration", "in_point", "fade_in", "fade_out",
                                                    "volume", "track_volume", "loop", "x", "y", "scale",
                                                    "opacity", "text", "font_size", "color"],
                                             "pos": ["bottom", "middle", "top"],
                                             "track": ["video", "overlay", "audio"],
                                             "kind": ["image", "video", "audio", "text"]}.items() for s in ss}
    missing = sorted(k for k in used | dynamic if k not in EN and not k.endswith("_"))
    assert missing == []


def test_missing_ffmpeg_disables_export(page):
    assert page.exe is None
    assert not page.btn_export.isEnabled()
    assert "not found" in page.ffmpeg_label.text()


def test_ffmpeg_path_saved_to_settings(page, monkeypatch, tmp_path):
    monkeypatch.setattr(ff, "find_ffmpeg", lambda configured=None: configured)
    monkeypatch.setattr(ff, "ffmpeg_version", lambda exe: "9.0")
    page.ffmpeg_path.setText("C:/tools/ffmpeg.exe")
    page._save_ffmpeg_path()
    assert page.store.get(ff.SETTINGS_KEY) == "C:/tools/ffmpeg.exe"
    assert page.exe == "C:/tools/ffmpeg.exe" and page.btn_export.isEnabled()


def test_add_split_delete_undo_redo(page, tmp_path):
    imgs = []
    for n in ("a.png", "b.png"):
        (tmp_path / n).write_bytes(b"x")
        imgs.append(str(tmp_path / n))
    assert page.add_files(imgs + [str(tmp_path / "notes.txt")]) == 2
    v = page.project.first_track("video")
    assert [(c.start, c.duration) for c in v.clips] == [(0, 3), (3, 3)]
    page.timeline.set_playhead(1.0)
    page.timeline.select(v.clips[0])
    page.split()
    assert len(page.project.first_track("video").clips) == 3
    page.timeline.select(page.project.first_track("video").clips[0])
    page.delete_selected()
    assert len(page.project.first_track("video").clips) == 2
    page.undo()
    assert len(page.project.first_track("video").clips) == 3
    page.undo()
    assert len(page.project.first_track("video").clips) == 2
    page.redo()
    assert len(page.project.first_track("video").clips) == 3
    assert page.dirty


def test_add_text_and_subtitle_panel(page):
    page.timeline.set_playhead(2.0)
    page.add_text()
    clip = page.project.first_track("overlay").clips[0]
    assert clip.kind == "text" and clip.start == 2.0
    assert page.inspector.clip is clip
    page.subs.add_cue()
    assert [(c.start, c.end) for c in page.project.cues] == [(2.0, 4.0)]
    assert page.subs.table.rowCount() == 1
    page.subs.table.item(0, 2).setText("Edited")
    assert page.project.cues[0].text == "Edited"
    page.subs.size.setValue(80)
    assert page.project.style.size == 80


def test_save_and_load_project(page, tmp_path):
    page.project.cues.append(Cue(0, 1, "x"))
    page.path = tmp_path / "p.lsproj"
    page.save()
    assert not page.dirty
    page.project.cues.clear()
    page.load(tmp_path / "p.lsproj")
    assert page.project.cues[0].text == "x"


def test_preview_paints(page, tmp_path):
    from PySide6.QtGui import QImage

    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(0xFF3366)
    img.save(str(tmp_path / "a.png"))
    page.add_files([str(tmp_path / "a.png")])
    page.project.cues.append(Cue(0, 2, "Hello"))
    page.preview.resize(320, 180)
    page.timeline.set_playhead(1.0)
    page.preview.grab()   # runs paintEvent
    page.timeline.resize(800, 200)
    page.timeline.grab()


def test_export_worker_in_thread(qapp, tmp_path):
    from PySide6.QtCore import QThread

    from src.editor.model import Clip, Project
    from src.ui.editor.export import ExportWorker

    class Proc:
        def __init__(self):
            import io
            self.stdout = io.StringIO("out_time_us=1000000\nout_time_us=2000000\nprogress=end\n")
            self.stdin = io.StringIO()

        def wait(self, timeout=None):
            return 0

    p = Project.new()
    p.first_track("video").clips.append(Clip("image", "a.png", duration=2))
    plan = ff.build_export(p, str(tmp_path / "o.mp4"))
    worker = ExportWorker("ffm", plan, tmp_path / "w", popen=lambda cmd, **kw: Proc())
    thread = QThread()
    worker.moveToThread(thread)
    got = {"progress": []}
    worker.progress.connect(lambda f: got["progress"].append(f))
    worker.finished.connect(lambda path: got.setdefault("done", path))
    thread.started.connect(worker.run)
    thread.start()
    deadline = time.monotonic() + 5
    while "done" not in got and time.monotonic() < deadline:
        qapp.processEvents()
    thread.quit()
    thread.wait()
    assert got["done"] == str(tmp_path / "o.mp4")
    assert got["progress"][-1] == 1.0 and 0.5 in got["progress"]


def test_main_window_registers_video_editor(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ff, "find_ffmpeg", lambda configured=None: None)
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow
    from src.ui.editor.page import VideoEditorPage

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    w = MainWindow()
    register_pages(w)
    assert isinstance(w.page("video_editor"), VideoEditorPage)
    w.close()
