"""A Production's Items as rows: one per Item, review state in the existing cells."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from fake_provider import FakeProvider
from src import config, projects, theme
from src.config import Settings
from src.gen.models import Job, JobStatus
from src.projects.store import job_to_row, row_to_job
from src.ui.generator.page import GeneratorPage
from src.ui.generator.prompt_model import COL_CHARACTER, COL_OUTPUT, COL_PROMPT, COL_STATUS, COLUMN_KEYS, REVIEW_COLORS, STATUS_COLORS, status_color
from src.web.engine_client import EngineError
from src.web.run_mirror import RunMirror, banner_text, item_fields

URL = "https://flow.google.com/project/prod"
SUMMARY = {
    "status": "waiting_review", "paused": None,
    "stages": {"reference": {"total": 4, "approved": 4}, "still": {"total": 8, "approved": 6}, "animation": {"total": 8, "approved": 0}},
    "credits": {"max": 60, "spent": 14, "planned": 20},
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(config, "_settings", settings)
    s = projects.install(settings)
    s.active.set_flow(URL, "")
    yield s
    projects.uninstall()


def item(state="pending_review", id_="IMG_01", stage="still", take=1, **extra):
    return {"type": "production.item", "runId": "r1", "production_id": "p1", "item": id_, "stage": stage, "state": state,
            "take": take, "approved_take": take if state == "approved" else None, "prompt": "a fox", "file": None,
            "ref_names": ["The narrator", "Bunker"], "stale": [], "error": None, "progress": None, "source": "phase", **extra}


def write_run(data: Path):
    run = data / "r1"
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(json.dumps({"id": "r1", "name": "Zombie Bunker", "dir": str(run), "flowProjectUrl": URL, "jobs": []}))
    (run / "production.json").write_text(json.dumps({"id": "p1"}))
    (data / "runs.jsonl").write_text(json.dumps({"dir": str(run)}) + "\n")


@pytest.fixture
def page(qapp, store, tmp_path):
    write_run(tmp_path)
    page = GeneratorPage("flow_image", FakeProvider())
    page.mirror = RunMirror(tmp_path, page_lookup=lambda project, key: page if key == "flow_image" else None)
    page.mirror.store = store
    yield page
    page.shutdown()


def cell(page, col, role=Qt.ItemDataRole.DisplayRole, row=0):
    return page.model.data(page.model.index(row, col), role)


@pytest.mark.parametrize("state,status,review", [
    ("planned", JobStatus.QUEUED, ""), ("generating", JobStatus.RUNNING, ""),
    ("pending_review", JobStatus.DONE, "pending_review"), ("approved", JobStatus.DONE, "approved"),
    ("rejected", JobStatus.DONE, "rejected"), ("regenerating", JobStatus.RUNNING, "regenerating"),
    ("failed", JobStatus.FAILED, ""),
])
def test_one_event_per_state_gives_one_row_with_the_mapped_status(page, state, status, review):
    page.mirror.apply_production_event(item("planned"))
    page.mirror.apply_production_event(item(state))
    assert len(page.jobs) == 1
    assert (page.jobs[0].status, page.jobs[0].review, page.jobs[0].origin) == (status, review, "agent")


def test_references_and_stills_land_on_image_animations_on_video(store, tmp_path):
    write_run(tmp_path)
    mirror = RunMirror(tmp_path)
    mirror.store = store
    for event in (item(id_="MD_01", stage="reference"), item(), item(id_="ANI_01", stage="animation")):
        mirror.apply_production_event(event)
    assert [r["item_id"] for r in store.active.rows("flow_image")] == ["MD_01", "IMG_01"]
    assert [r["item_id"] for r in store.active.rows("flow_video")] == ["ANI_01"]


def test_status_text_includes_the_take(page):
    page.mirror.apply_production_event(item(take=2))
    assert cell(page, COL_STATUS) == "Review v2"
    page.mirror.apply_production_event(item("approved", take=3))
    assert cell(page, COL_STATUS) == "Approved v3"


def test_approved_row_names_its_approved_take_not_the_newest(page):
    page.mirror.apply_production_event({**item("approved", take=3), "approved_take": 1})
    job = page.jobs[0]
    assert (job.take, job.latest_take) == (1, 3) and cell(page, COL_STATUS) == "Approved v1"


def test_colours_come_only_from_status_colors(page):
    # One source of colour: the status and review tables (Contact Sheet contract, 2026-11-03).
    allowed = set(STATUS_COLORS.values()) | set(REVIEW_COLORS.values())
    for state in ("planned", "generating", "pending_review", "approved", "rejected", "regenerating", "failed"):
        page.mirror.apply_production_event(item(state))
        assert status_color(page.jobs[0]) in allowed


def test_a_rejected_row_uses_the_marker(page):
    # A rejection is a decision, not a failure: red marker, rose stays for failed (R1 amended).
    page.mirror.apply_production_event(item("rejected"))
    assert status_color(page.jobs[0]) == REVIEW_COLORS["rejected"] == theme.tokens()["marker"]
    assert page.jobs[0].status is JobStatus.DONE
    assert cell(page, COL_STATUS, Qt.ItemDataRole.ForegroundRole).name() == theme.tokens()["marker"]


def test_prompt_cell_shows_id_and_edit_role_the_prompt_alone(page):
    page.mirror.apply_production_event(item())
    assert cell(page, COL_PROMPT) == "IMG_01 · a fox"
    assert cell(page, COL_PROMPT, Qt.ItemDataRole.EditRole) == "a fox"


def test_a_production_prompt_cell_isnt_editable_a_normal_row_still_is(page):
    page.mirror.apply_production_event(item())
    page.add_prompts(["plain"])
    editable = Qt.ItemFlag.ItemIsEditable
    assert not page.model.flags(page.model.index(0, COL_PROMPT)) & editable
    assert page.model.flags(page.model.index(1, COL_PROMPT)) & editable
    assert not page.model.setData(page.model.index(0, COL_PROMPT), "changed")


def test_character_cell_shows_the_cast(page):
    page.mirror.apply_production_event(item())
    assert cell(page, COL_CHARACTER) == "The narrator, Bunker"


def test_tooltip_names_the_stale_cause(page):
    page.mirror.apply_production_event(item("approved", stale=["MD_02"]))
    assert "MD_02" in cell(page, COL_STATUS, Qt.ItemDataRole.ToolTipRole)


def test_start_never_submits_a_production_row(page):
    page.mirror.apply_production_event(item("planned"))
    assert page.start() == 0 and page.jobs[0].status is JobStatus.QUEUED


def test_clear_and_remove_keep_production_rows(page):
    page.mirror.apply_production_event(item())
    page.add_prompts(["plain"])
    page.remove_rows([0])
    assert len(page.jobs) == 2
    page.clear()
    assert [j.item_id for j in page.jobs] == ["IMG_01"]


def test_stats_count_production_rows(page):
    page.mirror.apply_production_event(item("planned"))
    page.mirror.apply_production_event(item("failed", id_="IMG_02"))
    assert page.stats_header.stats["queued"] == 1 and page.stats_header.stats["failed"] == 1


def test_rows_round_trip():
    job = Job("a fox", origin="agent", production_id="p1", item_id="IMG_01", review="approved", take=2, latest_take=3,
              stale="MD_02", ref_labels=["A"], status=JobStatus.DONE)
    again = row_to_job(json.loads(json.dumps(job_to_row(job))), 1)
    assert (again.production_id, again.item_id, again.review, again.take, again.latest_take, again.stale, again.ref_labels) == \
        ("p1", "IMG_01", "approved", 2, 3, "MD_02", ["A"])


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING])
def test_a_production_row_isnt_forced_to_stopped(status):
    assert row_to_job(job_to_row(Job("x", production_id="p1", status=status)), 1).status is status
    assert row_to_job(job_to_row(Job("x", status=status)), 1).status is JobStatus.STOPPED


class FakeClient:
    def __init__(self, items, down=False):
        self.items, self.down = items, down

    def call(self, tool, args=None, timeout=60):
        if self.down:
            raise EngineError("down")
        assert tool == "flow_production_status" and args["detail"] == "full"
        start = args["cursor"]
        reply = {**SUMMARY, "name": "Zombie Bunker", "items": self.items[start:start + 1]}
        if start + 1 < len(self.items):
            reply["next_cursor"] = start + 1
        return reply


def test_closed_app_production_rebuilds_rows_on_reopen(qapp, store, tmp_path):
    write_run(tmp_path)
    items = [{k: v for k, v in item("approved", id_=i).items() if k not in ("type", "runId")} for i in ("IMG_01", "IMG_02")]
    mirror = RunMirror(tmp_path, client=FakeClient(items))
    mirror.store = store
    assert mirror.catch_up() is True
    qapp.processEvents()
    page = GeneratorPage("flow_image", FakeProvider())
    assert [(j.item_id, j.review) for j in page.jobs] == [("IMG_01", "approved"), ("IMG_02", "approved")]
    assert "waiting for your review" in page.banner_label.text()
    page.shutdown()


def test_engine_down_keeps_the_saved_rows(qapp, store, tmp_path):
    write_run(tmp_path)
    store.active.set_rows("flow_image", [job_to_row(Job("a fox", origin="agent", production_id="p1", item_id="IMG_01", review="approved", take=1, status=JobStatus.DONE))])
    mirror = RunMirror(tmp_path, client=FakeClient([], down=True))
    mirror.store = store
    assert mirror.catch_up() is False
    assert store.active.rows("flow_image")[0]["review"] == "approved"


def test_banner_shows_counts_credits_and_waiting():
    assert banner_text(SUMMARY, "Zombie Bunker") == \
        "Zombie Bunker: references 4/4 · stills 6/8 · animations 0/8 · 14 of 60 credits · waiting for your review"


def test_paused_reason_appears_in_the_banner(page):
    text = banner_text({**SUMMARY, "status": "paused", "paused": {"reason": "quote_drift"}}, "Z")
    assert "paused: quote drift" in text
    page.set_production_summary({**SUMMARY, "status": "paused", "paused": {"reason": "quota"}}, "Z")
    assert "paused: quota" in page.banner_label.text()


def test_banner_sits_beside_the_provider_banner(qapp, store):
    page = GeneratorPage("flow_image", FakeProvider(), banner="Provider says")
    page.set_production_summary(SUMMARY, "Z")
    assert page.banner_label.text().startswith("Provider says\nZ: ")
    page.shutdown()


def test_the_output_cell_for_an_animation_is_the_silent_file(tmp_path):
    fields = item_fields(item("pending_review", stage="animation", file="videos/x.mp4", takes=[{"original": "videos/_original/x.flow.mp4"}]))
    assert fields["outputs"] == [Path("videos/x.mp4")]


def test_a_take_under_review_shows_its_own_file_is_what_the_row_carries(page):
    page.mirror.apply_production_event(item(file="images/v2.jpg", take=2))
    assert page.jobs[0].outputs == [Path("images/v2.jpg")] and cell(page, COL_OUTPUT) in (None, "")


def test_column_count_and_keys_are_unchanged():
    assert COLUMN_KEYS == ("gen_col_index", "gen_col_prompt", "gen_col_character", "gen_col_scene", "gen_col_refs",
                           "gen_col_status", "gen_col_progress", "gen_col_output")
