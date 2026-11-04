"""The review controls: existing menu, keys and message box, with a fake engine client."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QInputDialog, QMessageBox

from fake_provider import FakeProvider
from src import config, projects
from src.config import Settings
from src.gen.models import Job, JobStatus
from src.ui.generator.page import GeneratorPage
from src.web.engine_client import EngineError, EngineToolError
from src.web.production_actions import ProductionActions


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = {}  # tool -> exception, used once
        self.delay = 0
        self.cost = 10

    def call(self, tool, args=None, timeout=60):
        time.sleep(self.delay)
        self.calls.append((tool, args))
        if tool in self.fail:
            raise self.fail.pop(tool)
        if tool == "flow_production_status":
            return {"items": [{"production_id": "p", "item": "IMG_01", "state": "approved", "take": 1, "approved_take": 1, "prompt": "new truth"}]}
        return {"take": 2, "estimated_credits": self.cost}

    def sent(self, tool):
        return [a for t, a in self.calls if t == tool]


@pytest.fixture
def boxes(monkeypatch):
    seen = {"question": [], "warning": [], "answer": QMessageBox.StandardButton.Yes}
    def question(_parent, _title, text):
        seen["question"].append(text)
        return seen["answer"]
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: seen["warning"].append(text))
    return seen


def make_page(tmp_path, monkeypatch, key="flow_image"):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(config, "_settings", settings)
    projects.install(settings)
    page = GeneratorPage(key, FakeProvider())
    page.client = FakeClient()
    page._actions = ProductionActions(page.client)
    return page


@pytest.fixture
def page(qapp, tmp_path, monkeypatch, boxes):
    page = make_page(tmp_path, monkeypatch)
    yield page
    settle(qapp)
    page.shutdown()
    projects.uninstall()


@pytest.fixture
def video(qapp, tmp_path, monkeypatch, boxes):
    page = make_page(tmp_path, monkeypatch, "flow_video")
    yield page
    settle(qapp)
    page.shutdown()
    projects.uninstall()


def settle(qapp):
    for _ in range(4):  # an action's reply can start the next action
        for thread in threading.enumerate():
            if thread.name == "production-action":
                thread.join(5)
        qapp.processEvents()


def row(item="IMG_01", review="pending_review", take=1, status=JobStatus.DONE):
    return Job("a fox", origin="agent", production_id="p", item_id=item, review=review, take=take, latest_take=take, status=status)


def labels(menu):
    return {a.text(): a for a in menu.actions() if a.text()}


def test_production_menu(page):
    page.model.add_jobs([row()])
    menu = labels(page.table._build_menu(0, [0]))
    assert {"Approve", "Reject", "Retry with same prompt", "Modify prompt and regenerate…", "Remove"} <= set(menu)
    assert not menu["Remove"].isEnabled()
    assert menu["Approve"].shortcut().toString() == "Ctrl+Return"
    assert "Attach character" not in " ".join(menu) and not any(a.menu() for a in page.table._build_menu(0, [0]).actions())


def test_a_normal_rows_menu_is_unchanged(page):
    page.add_prompts(["plain"])
    menu = labels(page.table._build_menu(0, [0]))
    assert {"Edit…", "Retry", "Remove"} <= set(menu) and not menu["Approve"].isEnabled() and menu["Remove"].isEnabled()  # no picture yet


def test_approve_is_enabled_only_with_a_pending_row(page):
    page.model.add_jobs([row(), row("IMG_02", review="approved")])
    assert labels(page.table._build_menu(1, [1]))["Approve"].isEnabled() is False
    assert labels(page.table._build_menu(1, [0, 1]))["Approve"].isEnabled() is True


def test_ctrl_return_approves_selected_rows(qapp, page):
    page.model.add_jobs([row(), row("IMG_02")])
    page.table.selectAll()
    page.table.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier))
    settle(qapp)
    sent = page.client.sent("flow_production_review")
    assert len(sent) == 1 and sent[0]["items"] == [{"id": "IMG_01", "take": 1}, {"id": "IMG_02", "take": 1}]
    assert sent[0]["action"] == "approve" and sent[0]["actor"] == "app"


def test_modify_is_single_row(page):
    page.model.add_jobs([row(), row("IMG_02")])
    assert labels(page.table._build_menu(0, [0, 1]))["Modify prompt and regenerate…"].isEnabled() is False


def test_retry_on_a_mixed_selection_routes_each_way(qapp, page):
    page.model.add_jobs([row()])
    page.add_prompts(["plain"])
    page.jobs[1].status = JobStatus.FAILED
    assert page.retry_rows([0, 1]) == 1
    settle(qapp)
    page.queue.stop()
    assert [a["item"] for a in page.client.sent("flow_production_regenerate")] == ["IMG_01"]


def test_retry_failed_routes_failed_production_rows(qapp, page):
    page.model.add_jobs([row(review="", status=JobStatus.FAILED), row("IMG_02")])
    page.retry_failed()
    settle(qapp)
    sent = page.client.sent("flow_production_regenerate")
    assert [a["item"] for a in sent] == ["IMG_01"] and sent[0]["auto_confirm"] is True and sent[0]["expected_take"] == 1


def dialog(monkeypatch, text, ok=True):
    seen = []
    def fake(_parent, _title, _label, raw):
        seen.append(raw)
        return text, ok
    monkeypatch.setattr(QInputDialog, "getMultiLineText", fake)
    return seen


def test_modify_opens_the_raw_prompt_and_sends_the_new_text(qapp, page, monkeypatch):
    page.model.add_jobs([row(take=3)])
    seen = dialog(monkeypatch, "a darker fox")
    page.edit_row(0)
    settle(qapp)
    sent = page.client.sent("flow_production_regenerate")[0]
    assert seen == ["a fox"] and sent["prompt"] == "a darker fox" and sent["expected_take"] == 3


def test_cancel_sends_nothing(qapp, page, monkeypatch):
    page.model.add_jobs([row()])
    dialog(monkeypatch, "x", ok=False)
    page.edit_row(0)
    settle(qapp)
    assert page.client.calls == []


def test_an_unchanged_prompt_acts_as_retry(qapp, page, monkeypatch):
    page.model.add_jobs([row()])
    dialog(monkeypatch, "a fox")
    page.edit_row(0)
    settle(qapp)
    assert "prompt" not in page.client.sent("flow_production_regenerate")[0]


def test_an_animation_shows_the_cost_first_no_sends_nothing(qapp, video, boxes):
    video.model.add_jobs([row("ANI_01")])
    boxes["answer"] = QMessageBox.StandardButton.No
    video.retry_rows([0])
    settle(qapp)
    assert "10 credits" in boxes["question"][0]
    assert [a.get("dry_run") for a in video.client.sent("flow_production_regenerate")] == [True]


def test_an_animation_yes_regenerates(qapp, video, boxes):
    video.model.add_jobs([row("ANI_01")])
    video.retry_rows([0])
    settle(qapp)
    assert [a.get("dry_run") for a in video.client.sent("flow_production_regenerate")] == [True, None]


def test_over_budget_offers_to_raise_and_retries_once_on_yes(qapp, video, boxes):
    video.model.add_jobs([row("ANI_01")])
    video.client.fail["flow_production_regenerate"] = EngineToolError("over", {
        "error_code": "BUDGET_EXCEEDED", "details": {"credits": 10, "remaining": 4, "max_credits": 60, "run_id": "r1"}})
    video.retry_rows([0])
    settle(qapp)
    assert "66" in boxes["question"][0]
    assert video.client.sent("flow_job_control") == [{"action": "set_budget", "run_id": "r1", "max_credits": 66}]
    assert len(video.client.sent("flow_production_regenerate")) == 2


def test_an_image_regeneration_shows_no_box(qapp, page, boxes):
    page.model.add_jobs([row()])
    page.retry_rows([0])
    settle(qapp)
    assert boxes["question"] == [] and "dry_run" not in page.client.sent("flow_production_regenerate")[0]


def test_review_conflict_refreshes_the_row_and_shows_the_message(qapp, page, boxes):
    page.model.add_jobs([row()])
    page.client.fail["flow_production_review"] = EngineToolError("taken", {"error_code": "REVIEW_CONFLICT"})
    page.approve_rows([0])
    settle(qapp)
    assert "taken" in boxes["warning"][0]
    assert page.jobs[0].review == "approved" and page.jobs[0].prompt == "new truth"


def test_engine_down_shows_the_message_and_leaves_the_row(qapp, page, boxes):
    page.model.add_jobs([row()])
    page.client.fail["flow_production_review"] = EngineError("not running")
    page.approve_rows([0])
    settle(qapp)
    assert "not running" in boxes["warning"][0] and page.jobs[0].review == "pending_review"


def test_no_action_blocks_the_gui_thread(qapp, page):
    page.model.add_jobs([row()])
    page.client.delay = 0.5
    started = time.monotonic()
    page.approve_rows([0])
    page.reject_rows([0])
    page.retry_rows([0])
    assert time.monotonic() - started < 0.2
    settle(qapp)


def test_the_row_changes_only_on_the_engines_event(qapp, page):
    page.model.add_jobs([row()])
    page.approve_rows([0])
    settle(qapp)
    assert page.jobs[0].review == "pending_review"


def _takes_row(tmp_path):
    from src.gen.models import Take
    from PIL import Image
    files = []
    for n in (1, 2):
        f = tmp_path / f"v{n}.png"
        Image.new("RGB", (32, 18), (n * 60, 0, 0)).save(f)
        files.append(f)
    job = row(review="pending_review", take=2)
    job.takes = [Take(1, "a fox", ["r.png"], "done", str(files[0]), 0, "rejected", "app", "2026-11-04T10:00:00Z"),
                 Take(2, "a red fox", [], "done", str(files[1]), 0)]
    job.outputs = [files[1]]
    return job


def test_older_take_can_be_approved(page, qapp, tmp_path):
    page.model.add_jobs([_takes_row(tmp_path)])
    panel = page.take_panel
    panel.show_rows(page.model, [0])
    assert [b.text() for b in panel.take_buttons] == ["T1", "T2"]
    assert panel.shown_take().n == 2
    panel.take_buttons[0].click()
    assert panel.shown_take().n == 1 and panel.btn_approve.text() == "Approve take 1"
    assert "rejected by app" in panel.take_info.text()
    panel.btn_approve.click()
    settle(qapp)
    assert page.client.sent("flow_production_review")[-1] == {
        "production_id": "p", "items": [{"id": "IMG_01", "take": 1}], "action": "approve", "actor": "app"}


def test_note_is_sent(page, qapp, tmp_path):
    page.model.add_jobs([_takes_row(tmp_path)])
    panel = page.take_panel
    panel.show_rows(page.model, [0])
    panel.note.setText("  better light  ")
    panel.btn_reject.click()
    settle(qapp)
    sent = page.client.sent("flow_production_review")[-1]
    assert sent["note"] == "better light" and sent["action"] == "reject" and sent["items"] == [{"id": "IMG_01", "take": 2}]
    assert panel.note.text() == ""


def test_compare_shows_two_takes(page, qapp, tmp_path):
    page.model.add_jobs([_takes_row(tmp_path)])
    viewer = page.viewer
    viewer.open_row(0, [0])
    assert viewer.canvas.label == "T2" and viewer.canvas_b.isHidden()
    viewer.toggle_compare()
    assert not viewer.canvas_b.isHidden() and viewer.canvas_b.label == "T1"
    assert viewer.canvas_b.verdict == "rejected" and viewer.canvas.pix is not None and viewer.canvas_b.pix is not None
    viewer.step_output(-1)  # stepping onto the compared take ends the compare
    assert viewer.canvas.label == "T1" and viewer.canvas_b.isHidden()
    viewer.verdict("approve")
    settle(qapp)
    assert page.client.sent("flow_production_review")[-1]["items"] == [{"id": "IMG_01", "take": 1}]


def test_rebate_badge_names_the_take():
    from src.ui.generator.sheet import take_badge
    job = row(take=2)
    assert take_badge(job) == "T2/2"
    assert take_badge(row(take=1)) == ""


def test_stale_filter(page):
    fresh, old = row("IMG_01"), row("IMG_02")
    old.stale = "REF_01"
    page.model.add_jobs([fresh, old])
    page.set_filter("stale")
    assert page.sheet.isRowHidden(0) and not page.sheet.isRowHidden(1)


def test_stages_are_grouped(page):
    jobs = [row("REF_01"), row("REF_02"), row("IMG_01")]
    jobs[0].production_stage = jobs[1].production_stage = "reference"
    jobs[2].production_stage = "still"
    page.model.add_jobs(jobs)
    assert [page.sheet.group_start(r) for r in range(3)] == ["reference", "", "still"]
    page.sheet.setRowHidden(0, True)
    assert page.sheet.group_start(1) == "reference"
    jobs[2].production_stage = "reference"
    assert [page.sheet.group_start(r) for r in range(1, 3)] == ["", ""]  # one stage needs no marks


def test_stage_survives_a_save():
    from src.projects.store import job_to_row, row_to_job
    from src.web.run_mirror import item_fields
    fields = item_fields({"production_id": "p", "item": "REF_01", "state": "pending_review", "stage": "reference"})
    job = Job("x", production_stage=fields["production_stage"])
    assert row_to_job(job_to_row(job), 1).production_stage == "reference"


def test_animate_from_still_sets_start_frame(page, video, tmp_path):
    still = tmp_path / "s.png"
    still.write_bytes(b"x")
    done = Job("a fox at dawn", status=JobStatus.DONE, outputs=[still])
    page.model.add_jobs([done])
    menu = labels(page.table._build_menu(0, [0]))
    sent = []
    page.animate_stills.connect(sent.append)
    menu["Animate from this still"].trigger()
    assert sent == [[("a fox at dawn", still)]]
    jobs = video.add_frame_shots(sent[0])
    assert jobs[0].start_frame == still and jobs[0].prompt == "a fox at dawn"
    assert "Animate from this still" not in labels(video.table._build_menu(0, [0]))


def test_last_frame_chains_next_row(video, qapp, tmp_path, monkeypatch):
    from src.editor import ffmpeg, stitch
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(stitch, "resolve_ffmpeg", lambda configured=None: "ffmpeg.exe")
    monkeypatch.setattr(ffmpeg.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    first, second = Job("one", status=JobStatus.DONE, outputs=[clip]), Job("two")
    video.model.add_jobs([first, second])
    labels(video.table._build_menu(0, [0]))["Use last frame as next start"].trigger()
    settle(qapp)
    assert calls and calls[0][:6] == ["ffmpeg.exe", "-y", "-v", "error", "-sseof", "-3"]
    assert second.start_frame == tmp_path / "c_last.png"
    labels(video.table._build_menu(1, [1]))  # a pending row has no clip to chain from
    video.take_panel.show_rows(video.model, [1])
    assert video.take_panel.frame_slots["start_frame"][0].text() == "c_last.png"
    video.set_frame(1, "start_frame", None)
    assert second.start_frame is None


def test_frames_and_references_stop_before_any_call(tmp_path, monkeypatch):
    from src.gen.provider import ProviderError
    import src.gen.web_flow_video as wfv
    caps = {"video": {"models": {"omni": {"credits": {"720p": {"8": 10}}}}, "defaultModel": "omni", "ratios": ["16:9"]}}
    monkeypatch.setattr(wfv, "capabilities", lambda: caps)
    job = Job("x", refs=[tmp_path / "r.png"], start_frame=tmp_path / "s.png")
    with pytest.raises(ProviderError, match="Frames can't be combined"):
        wfv.WebFlowVideoProvider().generate(job, {}, None)


def test_shot_override_changes_estimate(qapp, monkeypatch):
    import src.gen.web_flow_video as wfv
    caps = {"video": {"models": {"omni": {"credits": {"720p": {"8": 10, "4": 5}, "360p": {"8": 4}}}},
                      "defaultModel": "omni", "ratios": ["16:9"]}}
    monkeypatch.setattr(wfv, "capabilities", lambda: caps)
    a, b = Job("a"), Job("b")
    options = {"model": "omni", "duration": "8", "resolution": "720p", "count": 1}
    provider = wfv.WebFlowVideoProvider()
    assert provider.estimate([a, b], options).credits == 20
    b.overrides = {"duration": "4", "count": 2}
    assert provider.estimate([a, b], options).credits == 20  # 10 + 5 x 2
    b.overrides = {"resolution": "360p"}
    assert provider.estimate([a, b], options).credits == 14


def test_override_survives_project_reload():
    from src.projects.store import job_to_row, row_to_job
    job = Job("x", overrides={"duration": "4", "count": 2})
    assert row_to_job(job_to_row(job), 1).overrides == {"duration": "4", "count": 2}


def test_panel_sets_and_clears_a_shot_setting(page):
    page.add_prompts(["one"])
    panel = page.take_panel
    panel.show_rows(page.model, [0])
    assert not panel.shot.isHidden() and "count" in panel.shot_boxes
    box = panel.shot_boxes["count"]
    assert box.itemData(0) is None and box.itemText(0).startswith("Page setting")
    box.setCurrentIndex(box.findData(3))
    box.activated.emit(box.currentIndex())
    assert page.model.job_at(0).overrides == {"count": 3}
    panel.show_rows(page.model, [0])
    assert panel.shot_boxes["count"].currentData() == 3
    panel.shot_boxes["count"].setCurrentIndex(0)
    panel.shot_boxes["count"].activated.emit(0)
    assert page.model.job_at(0).overrides == {}


def test_shared_tally_survives_an_override():
    from src.gen.provider import shot_options
    options = {"count": 1}
    merged = shot_options(Job("x", overrides={"count": 2}), options)
    assert merged["count"] == 2 and merged["_shared"] is options
    assert shot_options(Job("y"), options) is options


CLIP_CAPS = {"video": {"models": {
    "omni": {"modes": ["text", "frames", "ingredients", "edit"], "editCredits": 20, "credits": {"720p": {"8": 10}}},
    "veoLite": {"modes": ["text", "frames", "ingredients", "extend"], "credits": {"720p": {"8": 6}}}},
    "defaultModel": "omni", "ratios": ["16:9"]}}


def _clip_row(tmp_path, url="https://labs.google/fx/tools/flow/project/p/edit/c1"):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    return Job("a fox runs", status=JobStatus.DONE, outputs=[clip], flow_url=url)


def test_extend_only_offered_for_supported_model(video, tmp_path, monkeypatch):
    import src.gen.web_flow_image as wfi
    monkeypatch.setattr(wfi, "capabilities", lambda: CLIP_CAPS)
    video.model.add_jobs([_clip_row(tmp_path)])
    video.config_panel.set_value("model", "omni")
    menu = labels(video.table._build_menu(0, [0]))
    assert "Edit this clip…" in menu and "Extend this clip…" not in menu
    video.model.job_at(0).overrides = {"model": "veoLite"}
    menu = labels(video.table._build_menu(0, [0]))
    assert "Extend this clip…" in menu and "Edit this clip…" not in menu
    video.model.job_at(0).flow_url = ""
    assert not labels(video.table._build_menu(0, [0]))["Extend this clip…"].isEnabled()


def test_edit_states_cost(video, tmp_path, monkeypatch):
    import src.gen.web_flow_image as wfi
    import src.gen.web_flow_video as wfv
    monkeypatch.setattr(wfi, "capabilities", lambda: CLIP_CAPS)
    monkeypatch.setattr(wfv, "capabilities", lambda: CLIP_CAPS)
    video.model.add_jobs([_clip_row(tmp_path)])
    video.config_panel.set_value("model", "omni")
    asked = []
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda _p, _t, label, _v: (asked.append(label), ("make it night", True))[1])
    shot = video.clip_mode(0, "edit")
    assert "20 credits" in asked[0]
    assert shot.video_mode == "edit" and shot.source_url.endswith("/c1") and shot.prompt == "make it night"
    assert wfv.WebFlowVideoProvider().estimate([shot], video.config_panel.values()).credits == 20


def test_extend_sends_its_source_and_nothing_else(tmp_path, monkeypatch):
    import src.gen.web_flow_video as wfv
    monkeypatch.setattr(wfv, "capabilities", lambda: CLIP_CAPS)
    sent = {}
    monkeypatch.setattr(wfv, "run_engine_job", lambda _p, _j, tool, args, *_a: sent.update(args) or [])
    shot = Job("then it jumps", video_mode="extend", source_url="u1")
    wfv.WebFlowVideoProvider().generate(shot, {"model": "veoLite", "duration": "8", "count": 3}, None)
    assert sent["extend_from"] == "u1" and sent["count"] == 1 and "ingredients" not in sent and sent["max_credits"] == 6
    with pytest.raises(wfv.ProviderError, match="can't extend"):
        wfv.WebFlowVideoProvider().generate(shot, {"model": "omni", "duration": "8"}, None)


def test_run_row_jumps_to_frames(page, qapp, tmp_path):
    from src.ui.generator.runs_panel import run_row
    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "images").mkdir(parents=True)
    inside = Job("in", status=JobStatus.DONE, outputs=[run_dir / "images" / "a.png"])
    outside = Job("out", status=JobStatus.DONE, outputs=[tmp_path / "b.png"])
    page.model.add_jobs([outside, inside])
    run = {"run_id": "r1", "name": "Ep 1", "total": 2, "counts": {"done": 1, "generating": 1},
           "kind": "video", "dir": str(run_dir), "credits": 20}
    page.runs_panel.show_runs([run])
    assert run_row(run) == ["Ep 1", "video", "1 of 2", "20", "running"]
    page.jump_to_run(run)
    assert page.table.selected_rows() == [1]
    page.jump_to_run({"dir": str(tmp_path / "nowhere")})
    assert page.runs_panel.note.text() == "None of this page's frames are in that run's folder."


def test_runs_tab_asks_the_engine(page, qapp):
    page.refresh_runs()
    settle(qapp)
    assert page.client.sent("flow_list_runs") == [{"limit": 20}]


def test_assemble_uses_approved_in_order(video, qapp, tmp_path, monkeypatch):
    from src.editor import stitch
    clips = [tmp_path / f"{n}.mp4" for n in "abc"]
    still = tmp_path / "s.png"
    video.model.add_jobs([
        Job("one", status=JobStatus.DONE, outputs=[clips[0]], review="approved"),
        Job("two", status=JobStatus.DONE, outputs=[clips[1]]),
        Job("still", status=JobStatus.DONE, outputs=[still], review="approved"),
        Job("three", status=JobStatus.DONE, outputs=[clips[2]], review="approved"),
    ])
    video._update_controls()
    assert video.btn_assemble.isEnabled()
    seen, opened = [], []

    def fake(spec, on_progress, should_stop):
        seen.append(spec)
        on_progress(0.5)
        return Path(spec.output)
    monkeypatch.setattr(stitch, "stitch", fake)
    monkeypatch.setattr(video, "_open", opened.append)
    video.assemble()
    settle(qapp)
    assert [c["path"] for c in seen[0].clips] == [str(clips[0]), str(clips[2])]
    assert opened == [Path(seen[0].output)] and Path(seen[0].output).parent.name == "final"
    assert video.btn_assemble.isEnabled()


def test_assemble_waits_for_an_approved_clip(video):
    video.model.add_jobs([Job("one", status=JobStatus.DONE, outputs=[Path("a.mp4")])])
    video._update_controls()
    assert not video.btn_assemble.isEnabled()
