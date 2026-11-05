"""S3-3: the run bar acts on the run it shows; held runs offer what fits their reason."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gen.models import Job, JobStatus
from src.i18n import tr
from src.web.production_actions import ActionError
from tests.test_contact_sheet import _Empty, _Provider, _Store
from src.ui.generator.page import GeneratorPage

YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


class Actions:
    def __init__(self, refuse=None):
        self.calls, self.refuse = [], refuse

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if self.refuse:
                raise self.refuse
            return {}
        return call


@pytest.fixture
def page(qapp, monkeypatch):
    page = GeneratorPage("flow_video", _Provider(), store=_Store(), characters=_Empty(), scenes=_Empty())
    page._actions = Actions()

    def act(work, done=None, jobs=(), failed=None):  # the same as _act, on this thread
        try:
            result = work()
        except ActionError as exc:
            (failed or (lambda e: page._action_failed(e, jobs)))(exc)
        else:
            if done:
                done(result)
    monkeypatch.setattr(page, "_act", act)
    return page


def summary(status="running", **paused):
    return {"runId": "r1", "status": status, "paused": paused or None, "credits": {"max": 60, "spent": 20}}


def asked(monkeypatch, answer=YES):
    texts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: texts.append(a[2]) or answer)
    return texts


def test_pause_calls_engine_for_a_production(page):
    page.set_production_summary(summary(), "Fox")
    assert page.btn_pause.isEnabled() and page.btn_stop.isEnabled()
    page.toggle_pause()
    assert page.actions.calls == [("pause", ("r1",), {})]
    assert page.run_actions.isHidden()


def test_quote_drift_button_needs_confirm(page, monkeypatch):
    page.set_production_summary(summary("paused", reason="quote_drift", quoted=30, estimate=20, item="shot-3"), "Fox")
    assert not page.btn_accept_quote.isHidden() and page.btn_raise_cap.isHidden()
    texts = asked(monkeypatch, NO)
    page.accept_quote()
    assert page.actions.calls == []
    assert texts == [tr("run_accept_quote_confirm", item="shot-3", old=20, new=30)]
    asked(monkeypatch, YES)
    page.accept_quote()
    assert page.actions.calls == [("resume", ("r1",), {"accept_quote": True})]


def test_resume_shows_engine_refusal(page, monkeypatch):
    page._actions = Actions(refuse=ActionError("FLOW_BLOCKED", "Flow still shows the block: unusual traffic"))
    page.set_production_summary(summary("paused", reason="stopped"), "Fox")
    assert not page.btn_resume_run.isHidden()
    asked(monkeypatch, YES)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    page.resume_run()
    assert warned == [tr("gen_engine_error", message="Flow still shows the block: unusual traffic")]


def test_cancel_states_spent_credits(page, monkeypatch):
    page.set_production_summary(summary(), "Fox")
    texts = asked(monkeypatch, YES)
    page.stop()
    assert texts == [tr("run_cancel_confirm")] and "spent" in texts[0]
    assert page.actions.calls == [("cancel", ("r1",), {})]


def test_own_queued_frame_can_be_cancelled(page):
    job = Job("a fox")
    job.status = JobStatus.QUEUED
    page.queue._pending.append(job)
    assert page.queue.cancel([job]) == [job] and job.status is JobStatus.STOPPED
    assert job not in page.queue._pending


def test_held_run_shows_play_icon(page):
    """L5: a held run read 'Resume' only in the tooltip; the glyph stayed the pause bars."""
    page.set_production_summary(summary(), "Fox")
    assert page.btn_pause.property("icon_name") == "pause"
    page.set_production_summary(summary("paused", reason="user"), "Fox")
    assert page.btn_pause.property("icon_name") == "play"


def test_dialogs_title_with_page_name_not_key(qapp, monkeypatch):
    """L5: the Start confirm was titled 'flow_video'."""
    page = GeneratorPage("flow_video", _Provider(), title="Flow Video", store=_Store(), characters=_Empty(),
                         scenes=_Empty())
    assert page.dialog_title == "Flow Video"
