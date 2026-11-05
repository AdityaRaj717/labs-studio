"""Productions page (S5-1) with a fake engine client: plan, gates, cap, confirm, stale files."""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QMessageBox

from src import projects
from src.ui.production.page import ProductionsPage, default_cap
from src.web.production_actions import ProductionActions
from test_review_controls import FakeClient, settle

PLAN = {"ok": True, "plan_id": "abc123", "mode": "mixed", "counts": {"references": 2, "stills": 3, "animations": 2},
        "cast": [{"id": "REF_A", "name": "Ava", "kind": "character"}], "errors": [], "warnings": [],
        "analysis_needed": [], "implied": [], "estimate": {"credits": 101, "eta_minutes": 12}}


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    seen = {"question": [], "answer": QMessageBox.StandardButton.Yes, "pages": []}
    def question(_p, _t, text):
        seen["question"].append(text)
        return seen["answer"]
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a: None)
    projects.uninstall()
    pg = ProductionsPage(seen["pages"].append)
    pg.client = FakeClient()
    pg.client.replies["flow_production_plan"] = PLAN
    pg.client.replies["flow_production_start"] = {"production_id": "p", "run_id": "r1", "status": "running"}
    pg._actions = ProductionActions(pg.client)
    for name in ("mood.md", "shots.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    pg.moodboard_edit.setText(str(tmp_path / "mood.md"))
    pg.prompts_edit.setText(str(tmp_path / "shots.md"))
    pg.seen = seen
    yield pg
    settle(qapp)


def check(page, qapp, reply=None):
    if reply is not None:
        page.client.replies["flow_production_plan"] = reply
    page.check_plan(); settle(qapp)


def ready(page, qapp, reply=None):
    check(page, qapp, reply)
    page.cast_confirmed.setChecked(True)


def test_default_cap_is_estimate_plus_20(page, qapp):
    assert default_cap(101) == 122 and default_cap(0) == 0 and default_cap(10) == 12
    check(page, qapp)
    assert page.cap.value() == 122 and page.cap.minimum() == 101  # never below the estimate
    page.cap.setValue(50)
    assert page.cap.value() == 101


def test_plan_errors_block_start(page, qapp):
    bad = {**PLAN, "ok": False, "plan_id": None,
           "errors": [{"file": "C:/x/shots.md", "line": 12, "code": "PROMPT_FILE_INVALID", "message": "Shot IMG_02 needs kind"}]}
    ready(page, qapp, bad)
    assert not page.start_btn.isEnabled()
    assert "shots.md:12" in page.errors_label.text() and "Shot IMG_02 needs kind" in page.errors_label.text()
    ready(page, qapp, {**PLAN, "analysis_needed": [{"item": "REF_B", "reason": "Is this a character or a place?"}]})
    assert not page.start_btn.isEnabled() and "REF_B" in page.questions_label.text()
    page.start(); settle(qapp)
    assert page.client.sent("flow_production_start") == []


def test_start_needs_confirm(page, qapp):
    check(page, qapp)
    assert not page.start_btn.isEnabled()  # cast not confirmed yet
    page.cast_confirmed.setChecked(True)
    page.seen["answer"] = QMessageBox.StandardButton.No
    page.start(); settle(qapp)
    assert page.client.sent("flow_production_start") == []
    assert "5 shots" in page.seen["question"][0] and "101" in page.seen["question"][0] and "122" in page.seen["question"][0]


def test_start_sends_cap_and_gates(page, qapp):
    ready(page, qapp)
    page.cap.setValue(150)
    page.gate_stills.setChecked(False)
    page.start(); settle(qapp)
    (args,) = page.client.sent("flow_production_start")
    assert args == {"plan_id": "abc123", "cast_confirmed": True, "auto_confirm": True, "max_credits": 150,
                    "gates": {"references": True, "stills": False}}
    assert page.seen["pages"] == ["flow_video"]


def test_stills_only_goes_to_image_without_cap(page, qapp):
    ready(page, qapp, {**PLAN, "mode": "stills_only", "counts": {"references": 1, "stills": 2, "animations": 0},
                       "estimate": {"credits": 0}})
    page.start(); settle(qapp)
    (args,) = page.client.sent("flow_production_start")
    assert "max_credits" not in args and page.seen["pages"] == ["flow_image"]


def test_stale_plan_needs_recheck(page, qapp, tmp_path):
    ready(page, qapp)
    assert page.start_btn.isEnabled()
    target = tmp_path / "shots.md"
    st = os.stat(target)
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    page._update_start()
    assert not page.start_btn.isEnabled()
    page.start(); settle(qapp)
    assert page.client.sent("flow_production_start") == []
    check(page, qapp)
    assert page.start_btn.isEnabled()
