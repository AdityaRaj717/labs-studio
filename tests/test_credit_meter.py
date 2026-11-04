"""S3-1: the credit meter labels what it knows and how old it is."""

from __future__ import annotations

from datetime import datetime, timezone

from src.i18n import tr
from src.ui.generator.credit_meter import CreditMeter, meter_text, stale

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
STATUS = {"balance": 1240, "balanceAt": "2026-11-04T10:00:00.000Z",
          "ledger": {"monthTotal": 180, "todayQuota": {"m": {"model": "Imagen 4", "used": 8, "limit": 50, "remaining": 42}}}}


def test_meter_labels_stale_balance(qapp):
    text = meter_text(STATUS, NOW)
    assert tr("meter_balance", n="1,240") + " (" + tr("meter_age_h", n=2) + ")" in text
    assert tr("meter_month", n="180") in text and "Imagen 4 42 of 50" in text
    assert stale(STATUS, NOW)
    assert not stale({**STATUS, "balanceAt": "2026-11-04T11:55:00Z"}, NOW)
    assert stale({**STATUS, "balance": None}, NOW)
    meter = CreditMeter(lambda: STATUS, lambda: True)
    meter.show_status({**STATUS, "balanceAt": "2026-01-01T00:00:00Z"})
    assert meter.property("stale") is True
    meter.show_status(None)
    assert meter.text() == tr("meter_unreachable")


def test_meter_hidden_for_non_flow(qapp):
    from tests.test_contact_sheet import _Empty, _Provider, _Store
    from src.ui.generator.page import GeneratorPage

    page = GeneratorPage("flow_image", _Provider(), store=_Store(), characters=_Empty(), scenes=_Empty())
    assert page.credit_meter.isHidden()
    calls = []
    page.credit_meter.fetch = lambda: calls.append(1) or STATUS
    page.credit_meter.refresh()
    assert calls == []  # hidden: never asks Flow


def test_meter_waits_while_the_tab_is_busy(qapp):
    calls = []
    meter = CreditMeter(lambda: calls.append(1) or STATUS, lambda: False)
    meter.show()
    meter.refresh()
    assert calls == []


def test_meter_reads_again_once_the_tab_is_free(qapp):
    """L5: at the end of a run the engine still held the tab, the refresh was dropped and the meter
    kept the balance from before the run (830 after 24 more credits went out)."""
    meter = CreditMeter(lambda: STATUS, lambda: False)
    meter.show()
    meter.refresh()
    assert meter._retry.isActive()  # asks again later instead of giving up


def test_meter_age_moves_on_without_a_new_read(qapp, monkeypatch):
    """L5: '(just now)' stayed on screen for many minutes; the age is redrawn from the kept status."""
    import src.ui.generator.credit_meter as cm
    meter = CreditMeter(lambda: STATUS, lambda: True)
    meter.show_status(STATUS)
    monkeypatch.setattr(cm, "meter_text", lambda status, now=None: "later")
    meter._redraw()
    assert meter.text() == "later"
