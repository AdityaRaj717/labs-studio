"""S6-2: thumbnails decode on a pool, never in paint; the cache is byte-capped and follows mtime."""

from __future__ import annotations

import os
import threading

import pytest
from PySide6.QtGui import QColor, QImage

from src.gen.models import Job
from src.ui.generator import thumbs
from src.ui.generator.prompt_model import COL_OUTPUT, PromptTableModel
from src.ui.generator.sheet import SheetView
from src.ui.generator.thumbs import ThumbService, service


def _image(path, color="#808080", w=600, h=400):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return path


@pytest.fixture
def sheet(qapp, tmp_path):
    model = PromptTableModel()
    jobs = [Job(f"p{i}") for i in range(4)]
    for i, job in enumerate(jobs):
        job.outputs = [_image(tmp_path / f"{i}.png")]
    model.add_jobs(jobs)
    view = SheetView(model)
    view.resize(1100, 700)
    yield view
    view.deleteLater()


def test_paint_never_decodes(sheet, monkeypatch):
    threads = []
    real = thumbs._read

    def spy(*args):
        threads.append(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(thumbs, "_read", spy)
    sheet.grab()  # paint asks for every visible frame
    service().wait()
    sheet.grab()  # second paint draws what landed
    assert threads and threading.get_ident() not in threads


def test_missing_file_paints_blank(qapp, tmp_path):
    svc = ThumbService()
    gone = tmp_path / "gone.png"
    assert svc.get(gone, 240, 160) is None
    svc.wait()
    assert svc.get(gone, 240, 160) is None and svc.pool.activeThreadCount() == 0  # known missing: no requeue
    assert str(gone) in svc.missing


def test_regenerated_file_replaces_thumb(qapp, tmp_path):
    path = _image(tmp_path / "r.png", "#ff0000")
    model = PromptTableModel()
    job = Job("x")
    job.outputs = [path]
    model.add_jobs([job])
    svc = service()
    svc.get(path, 240, 160)
    svc.wait()
    assert svc.get(path, 240, 160).toImage().pixelColor(5, 5).red() > 200
    _image(path, "#0000ff")
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    model.refresh_job(job.id)  # the job update stats the file again
    svc.get(path, 240, 160)
    svc.wait()
    assert svc.get(path, 240, 160).toImage().pixelColor(5, 5).blue() > 200


def test_cache_respects_byte_cap(qapp, tmp_path):
    cap = 3 * 240 * 160 * 4
    svc = ThumbService(cap_bytes=cap)
    paths = [_image(tmp_path / f"{i}.png") for i in range(8)]
    for p in paths:
        svc.get(p, 240, 160)
    svc.wait()
    assert 0 < svc.bytes <= cap and len(svc._lru) < len(paths)


def test_dpr_change_refetches_thumbs(qapp, tmp_path):
    svc = ThumbService()
    path = _image(tmp_path / "d.png", w=1200, h=800)
    svc.get(path, 240, 160, 1.0)
    svc.wait()
    one = svc.get(path, 240, 160, 1.0).width()
    near = svc.get(path, 240, 160, 2.0)  # the 1x thumb, drawn scaled, while 2x decodes
    assert near is not None and near.width() == one
    svc.wait()
    two = svc.get(path, 240, 160, 2.0)
    assert two.width() == 2 * one and round(two.deviceIndependentSize().width()) == 240


def test_ready_repaints_one_rect(sheet, monkeypatch):
    model = sheet.model()
    calls = []
    vp = sheet.viewport()
    monkeypatch.setattr(vp, "update", lambda *a: calls.append(a))
    service().ready.emit(str(model.job_at(2).outputs[0]))
    assert calls == [(sheet.visualRect(model.index(2, COL_OUTPUT)),)]
