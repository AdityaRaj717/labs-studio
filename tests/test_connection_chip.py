"""S3-4: the rail chip says which account and project the engine is on, and the doctor answers inline."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from src.i18n import tr
from src.ui.connection_chip import ConnectionChip, chip_label, doctor_text

SIGNED_IN = {"browser": True, "account": "owner@example.com", "accountStatus": "ok", "flowAccessible": True,
             "oauthRequired": False, "pageTitle": "Fox film - Flow"}


def test_chip_reflects_login_state(qapp):
    assert chip_label(SIGNED_IN) == ("owner@example.com · Fox film", True)
    assert chip_label({**SIGNED_IN, "oauthRequired": True}) == (tr("chip_sign_in"), False)
    assert chip_label({**SIGNED_IN, "accountStatus": "mismatch"}) == (tr("chip_sign_in"), False)
    assert chip_label({"browser": False}) == (tr("chip_no_chrome"), False)
    assert chip_label(None) == (tr("chip_engine_off"), False)

    calls = []
    chip = ConnectionChip(lambda *a: calls.append(a) or SIGNED_IN, lambda: None)
    chip.refresh(idle=False, running=True)
    chip.refresh(idle=True, running=False)
    assert calls == [] and chip.label == tr("chip_engine_off")  # never asks a busy tab or a stopped engine
    chip.show_status(SIGNED_IN)
    assert chip.connected and chip.toolTip() == "owner@example.com · Fox film"


def test_running_engine_with_a_busy_tab_is_not_called_off(qapp):
    """Seen live 2026-11-04: a job held the tab from launch, and the chip said 'engine off' while it ran."""
    calls = []
    chip = ConnectionChip(lambda *a: calls.append(a) or SIGNED_IN, lambda: None)
    chip.refresh(idle=False, running=True)
    assert calls == [] and chip.label == tr("chip_engine_busy")
    chip.show_status(SIGNED_IN)
    chip.refresh(idle=False, running=True)
    assert chip.label == "owner@example.com · Fox film"  # a real read is kept while the tab is busy
    chip.refresh(idle=False, running=False)
    assert chip.label == tr("chip_engine_off")


def test_doctor_results_inline(qapp, monkeypatch):
    failed = {"ok": False, "checked": 12, "missing": [{"key": "prompt.box", "where": "project page"}]}
    text = doctor_text(failed)
    assert text.startswith(tr("chip_doctor_failed", n=1, checked=12)) and "prompt.box (project page)" in text
    assert doctor_text({"ok": True, "checked": 12}) == tr("chip_doctor_ok", n=12)

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    ConnectionChip(lambda *a: {}, lambda: None).show_doctor(failed)
    assert shown == [text]
