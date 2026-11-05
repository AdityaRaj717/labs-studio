"""The contact sheet shell: one selection, filters, local decisions, wrapping toolbar, palette."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from src.gen.models import JobStatus
from src.gen.provider import Provider
from src.ui.generator.page import GeneratorPage
from src.ui.generator.sheet import FILTERS
from src.ui.kit import FlowLayout
from src.i18n import tr


class _Provider(Provider):
    key = "fake"
    name = "Fake"

    def config_fields(self):
        return []

    def generate(self, job, options, on_progress):
        return []


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


@pytest.fixture
def page(qapp, tmp_path):
    page = GeneratorPage("flow_image", _Provider(), store=_Store(), characters=_Empty(), scenes=_Empty())
    jobs = page.add_prompts(["one", "two", "three"])
    jobs[0].status = jobs[1].status = JobStatus.DONE
    jobs[0].outputs = [Path(tmp_path / "a.png")]
    jobs[2].status = JobStatus.FAILED
    page.model.refresh_all()
    yield page
    page.shutdown()


class _Empty:
    def all(self):
        return []

    def get(self, _id):
        return None


def test_sheet_and_queue_share_one_selection(page):
    assert page.sheet.selectionModel() is page.table.selectionModel()
    page.select_row(1)
    assert page.table.selected_rows() == [1] and page.sheet.selected_rows() == [1]


def test_filters_hide_rows_in_both_views_and_count(page):
    page.set_filter("failed")
    assert page.sheet.visible_count() == 1 and page.table.isRowHidden(0) and not page.table.isRowHidden(2)
    page.set_filter("all")
    assert page.sheet.visible_count() == 3 and not page.table.isRowHidden(0)
    assert FILTERS["review"](page.jobs[0]) and not FILTERS["review"](page.jobs[2])
    assert page.filter_bar.buttons["failed"].text().endswith(" 1")


def test_an_empty_filter_says_so_and_a_cleared_page_offers_the_ways_in(page):
    page.set_filter("approved")
    assert page.views.currentWidget() is page.filter_empty
    page.set_filter("all")
    assert page.views.currentWidget() is page.sheet
    page.clear()
    assert page.views.currentWidget() is page.empty


def test_a_local_still_is_approved_rejected_and_taken_back(page):
    page.approve_rows([0])
    assert page.jobs[0].review == "approved"
    page.approve_rows([0])
    assert page.jobs[0].review == ""
    page.reject_rows([0, 2])  # a failed row has no picture to decide on
    assert page.jobs[0].review == "rejected" and page.jobs[2].review == ""


def test_a_decided_frame_hands_the_selection_on_inside_a_filter(page):
    page.set_filter("review")
    page.select_row(0)
    page.approve_rows([0])
    assert page.table.selected_rows() == [1]


def test_retrying_a_finished_frame_asks_first(page, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: (asked.append(a), QMessageBox.StandardButton.No)[1])
    monkeypatch.setattr(page, "retry_rows", lambda rows: pytest.fail("retried without a yes"))
    page._confirm_retry([0])
    assert asked


def test_retry_clears_the_mark(page):
    page.jobs[1].review = "approved"
    page.queue.retry = lambda jobs: len(jobs)
    page._retry([page.jobs[1]])
    assert page.jobs[1].review == ""


def test_the_viewer_walks_only_what_the_filter_shows(page):
    page.set_filter("review")
    page.open_viewer(0)
    assert page.surface.currentWidget() is page.viewer and page.viewer.rows == [0, 1]
    page.viewer.step(1)
    assert page.table.selected_rows() == [1]
    page.close_viewer()
    assert page.surface.currentWidget() is page.desk


def test_frame_width_and_view_persist(page):
    page.size_slider.setValue(300)
    page.set_view("queue")
    assert page._prefs.get("pages.flow_image.frame_width") == 300
    assert page._prefs.get("pages.flow_image.view") == "queue"
    assert page.views.currentWidget() is page.table


def test_flow_layout_wraps_and_keeps_every_widget_inside(qapp):
    holder = QWidget()
    layout = FlowLayout(holder)
    buttons = [QPushButton("a long button label") for _ in range(4)]
    for b in buttons:
        layout.addWidget(b)
    width = buttons[0].sizeHint().width() * 2 + 10
    height = layout.heightForWidth(width)
    assert height >= buttons[0].sizeHint().height() * 2
    layout.setGeometry(QRect(0, 0, width, height))
    assert all(b.geometry().right() <= width for b in buttons)
    assert len({b.geometry().y() for b in buttons}) == 2


# ---- S1-2: confirm before Start ---------------------------------------------
def _answer(monkeypatch, button):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: (asked.append(a[2]), button)[1])
    return asked


def test_start_asks_first_and_no_starts_nothing(page, monkeypatch):
    page.add_prompts(["four"])
    asked = _answer(monkeypatch, QMessageBox.StandardButton.No)
    monkeypatch.setattr(page, "start", lambda: pytest.fail("started without a yes"))
    page.btn_start.setEnabled(True)
    page.btn_start.click()
    assert asked


def test_start_confirm_counts_only_own_pending(page, monkeypatch):
    mine, agents = page.add_prompts(["four", "five"])
    agents.origin = "agent"
    asked = _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    started = []
    monkeypatch.setattr(page, "start", lambda: started.append(1) or 1)
    page._confirm_start()
    assert started and tr("gen_start_confirm_shots", shots=1) in asked[0]


def _video_page(qapp):
    from src.gen.web_flow_video import WebFlowVideoProvider

    page = GeneratorPage("flow_video", WebFlowVideoProvider(), store=_Store(), characters=_Empty(), scenes=_Empty())
    page.add_prompts(["a", "b"])
    return page


def test_video_confirm_states_credits(qapp, monkeypatch):
    page = _video_page(qapp)
    try:
        for key, value in {"model": "omni", "resolution": "720p", "duration": "8", "count": 2}.items():
            page.config_panel.set_value(key, value)
        asked = _answer(monkeypatch, QMessageBox.StandardButton.No)
        page._confirm_start()
        assert "48" in asked[0] and tr("gen_start_confirm_quote") in asked[0]  # 12 x 2 takes x 2 shots
    finally:
        page.shutdown()


def test_impossible_mix_stops_before_start(qapp, monkeypatch):
    page = _video_page(qapp)
    try:
        page.config_panel.set_value("model", "veoLite")
        page.config_panel.set_value("resolution", "360p")
        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
        monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("asked about an impossible mix"))
        monkeypatch.setattr(page, "start", lambda: pytest.fail("started an impossible mix"))
        assert page._confirm_start() == 0 and warned
    finally:
        page.shutdown()


def test_veo_offers_only_its_durations(qapp):
    page = _video_page(qapp)
    try:
        combo = page.config_panel.editors["duration"]
        page.config_panel.set_value("model", "veoFast")
        assert [combo.itemData(i) for i in range(combo.count())] == ["8"]
        page.config_panel.set_value("model", "omni")
        assert [combo.itemData(i) for i in range(combo.count())] == ["4", "6", "8", "10"]
        assert page.config_panel.editors["count"].maximum() == 4
    finally:
        page.shutdown()


# ---- S1-4: table and shell fixes ---------------------------------------------
def test_selected_failed_keeps_its_colour(page, qapp):
    from PySide6.QtGui import QColor

    from src import theme
    from src.ui.generator.prompt_model import COL_STATUS

    page.set_view("queue")
    page.table.setStyleSheet(theme.build_qss(theme.current_mode()))
    page.resize(1200, 600)
    page.show()
    page.select_row(2)
    qapp.processEvents()
    rect = page.table.visualRect(page.model.index(2, COL_STATUS))
    image = page.table.viewport().grab(rect).toImage()
    failed = QColor(theme.tokens()["failed"])

    def near(c):
        return abs(c.red() - failed.red()) + abs(c.green() - failed.green()) + abs(c.blue() - failed.blue()) < 60

    hits = sum(near(image.pixelColor(x, y)) for x in range(image.width()) for y in range(image.height()))
    page.hide()
    assert hits > 10


def test_help_icon_turns_to_frame_ink_on_the_viewer(page):
    from src.ui.help.button import attach_help_button

    btn = attach_help_button(page, "flow_image", lambda topic: None)
    page.open_viewer(0)
    assert btn.property("icon_token") == "frame_text"
    page.close_viewer()
    assert btn.property("icon_token") == "text"


def test_selected_row_stays_in_view_after_inspector_toggle(page, qapp):
    page.add_prompts([f"row {i}" for i in range(60)])
    page.set_view("queue")
    page.resize(1200, 500)
    page.show()
    qapp.processEvents()
    page.select_row(55)
    qapp.processEvents()
    for _ in range(2):
        page.toggle_inspector()
        qapp.processEvents()
        qapp.processEvents()
        rect = page.table.visualRect(page.model.index(55, 1))
        assert page.table.viewport().rect().intersects(rect)
    page.hide()


@pytest.mark.parametrize("width", [900, 1280, 1920])
def test_cells_fill_the_row(page, qapp, width):
    page.add_prompts([f"row {i}" for i in range(40)])
    sheet = page.sheet
    sheet.set_frame_width(240)
    sheet.resize(width, 600)
    sheet.show()
    qapp.processEvents()
    sheet.doItemsLayout()
    rights = [sheet.visualRect(sheet.model().index(r, sheet.modelColumn())).right() for r in range(10)]
    gutter = sheet.viewport().width() - 1 - max(rights)
    sheet.hide()
    assert 0 <= gutter <= sheet.spacing() * 2  # the trailing spacing plus at most one spacing of slack


def test_output_thumb_uses_device_ratio(page, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QPixmap

    from src.ui.generator import prompt_model
    from src.ui.generator.prompt_model import THUMB_HEIGHT

    path = tmp_path / "t.png"
    pix = QPixmap(600, 400)
    pix.fill(QColor("#808080"))
    pix.save(str(path))
    monkeypatch.setattr(prompt_model, "device_ratio", lambda: 2.0)
    from src.ui.generator.thumbs import service

    assert page.model._thumb(path) is None  # decoding is queued, never done in data()
    service().wait()
    thumb = page.model._thumb(path)
    # drawn at the row height, with at least 2x pixels (the 80 px width bucket may hold more)
    assert round(thumb.deviceIndependentSize().height()) == THUMB_HEIGHT and thumb.height() >= THUMB_HEIGHT * 2


def test_failure_text_is_not_drawn_in_the_output_cell(page):
    from PySide6.QtCore import Qt

    from src.ui.generator.prompt_model import COL_OUTPUT

    page.jobs[2].error = "Flow refused"
    index = page.model.index(2, COL_OUTPUT)
    assert page.model.data(index, Qt.ItemDataRole.DisplayRole) in (None, "")
    assert page.model.data(index, Qt.ItemDataRole.ToolTipRole) == "Flow refused"


def test_run_notice_is_amber_only_while_running(page):
    page.set_production_summary({"status": "running"}, "Ep 1")
    assert page.run_notice.property("live") is True
    page.set_production_summary({"status": "complete"}, "Ep 1")
    assert page.run_notice.property("live") is False


def test_retry_disabled_on_running_frame(page):
    page.jobs[0].status = JobStatus.RUNNING
    page.model.refresh_all()
    page.select_row(0)
    assert not page.take_panel.btn_retry.isEnabled()
    page.select_row(1)
    assert page.take_panel.btn_retry.isEnabled()


def _old_group_start(sheet, row):
    """The per-paint algorithm the cache replaced, kept here as the reference."""
    model = sheet.model()
    stage = model.job_at(row).production_stage
    if not stage:
        return ""
    stages = {model.job_at(r).production_stage for r in range(model.rowCount()) if not sheet.isRowHidden(r)}
    if len(stages - {""}) < 2:
        return ""
    for r in range(row):
        if not sheet.isRowHidden(r) and model.job_at(r).production_stage == stage:
            return ""
    return stage


@pytest.mark.parametrize("filter_key", ["all", "review", "failed"])
def test_group_start_cache_matches_the_old_algorithm(page, filter_key):
    jobs = page.add_prompts(["four", "five", "six"])
    for job, stage in zip(page.jobs, ["", "reference", "still", "reference", "still", "animation"]):
        job.production_stage = stage
    jobs[0].status = JobStatus.DONE
    page.model.refresh_all()
    page.set_filter(filter_key)
    for row in range(page.model.rowCount()):
        assert page.sheet.group_start(row) == _old_group_start(page.sheet, row)


def test_rating_and_label_keys_set_fields_and_persist(page):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from src.projects.store import job_to_row, row_to_job

    def press(key):
        page.sheet.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    page.select_row(0)
    press(Qt.Key.Key_4)
    press(Qt.Key.Key_8)
    job = page.jobs[0]
    assert (job.rating, job.label) == (4, "green")
    press(Qt.Key.Key_8)
    press(Qt.Key.Key_6)
    assert job.label == "red"
    back = row_to_job(job_to_row(job), 1)
    assert (back.rating, back.label) == (4, "red")
    assert row_to_job({"prompt": "old file"}, 1).rating == 0  # rows saved before marks still load
    press(Qt.Key.Key_0)
    assert job.rating == 0
    page.model.flush()
    assert page.filter_bar.buttons["labelled"].text().endswith("1")


def test_density_cycle_changes_the_cell_height(page):
    sheet = page.sheet
    heights = {}
    for _ in range(3):
        heights[sheet.density] = sheet.frame_size().height()
        sheet.cycle_density()
    assert sheet.density == 1
    assert heights[0] < heights[1] < heights[2]


def test_lights_cycle_and_escape(qapp):
    from src.ui.main_window import LIGHTS, MainWindow

    w = MainWindow()
    try:
        levels = []
        for _ in range(3):
            w.cycle_lights()
            levels.append(LIGHTS[w.lights][0])
        assert levels == ["dim", "out", "full"]
        w.set_lights(2)
        assert w._lights_esc.isEnabled()
        w._lights_esc.activated.emit()
        assert w.lights == 0 and not w._lights_esc.isEnabled()
    finally:
        w.close()


def test_lights_again_after_the_fade_ended(qapp):
    # The fade deletes itself when it ends; a second L after that must not touch the deleted animation.
    from PySide6.QtTest import QTest
    from src.ui.main_window import MainWindow

    w = MainWindow()
    try:
        w.cycle_lights()
        QTest.qWait(300)
        w.cycle_lights()
        assert w.lights == 2
    finally:
        w.close()
