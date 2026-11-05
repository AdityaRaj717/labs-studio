"""S2-5: the engine's own state (pause, outage, agent runs) shows on the desk."""

from __future__ import annotations

import json

import httpx

from src import config
from src.config import Settings
from src.i18n import tr
from src.web.engine_client import EngineClient, EngineHealth


def _window(qapp, tmp_path, monkeypatch):
    from src.app import register_pages
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("flow_image")
    return window


def test_engine_pause_shows_for_agent_run(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path, monkeypatch)
    window.set_engine_health(EngineHealth(ready=True, paused_reason="DAILY_MODEL_LIMIT", active=None))
    notice = window.page("flow_image").run_notice
    assert notice.text() == tr("engine_paused", reason="DAILY_MODEL_LIMIT")
    assert not notice.isHidden()
    window.set_engine_health(EngineHealth(ready=True))
    assert notice.isHidden()
    window.close()


def test_health_failure_shows_engine_down(qapp, tmp_path, monkeypatch):
    (tmp_path / "engine.json").write_text(json.dumps({"port": 1, "token": "t", "pid": 9}))

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refuse)
    health = EngineClient(tmp_path).health()
    assert health == EngineHealth(down=True)
    assert EngineClient(tmp_path / "none").health() is None  # never started: nothing to say

    window = _window(qapp, tmp_path, monkeypatch)
    window.set_engine_health(health)
    assert window.page("flow_image").run_notice.text() == tr("engine_down")
    window.close()


def test_rail_lights_for_agent_run(qapp, tmp_path, monkeypatch):
    window = _window(qapp, tmp_path, monkeypatch)
    lit = {}
    monkeypatch.setattr(window.sidebar, "set_live", lambda key, live: lit.__setitem__(key, live))
    window.set_engine_health(EngineHealth(ready=True, active="j1", active_kind="video"))
    assert lit == {"flow_image": False, "flow_video": True}
    window.set_engine_health(EngineHealth(ready=True))
    assert lit["flow_video"] is False
    window.close()


def test_health_reads_the_worker(tmp_path, monkeypatch):
    (tmp_path / "engine.json").write_text(json.dumps({"port": 1, "token": "t", "pid": 9}))
    body = {"ready": True, "uptimeMs": 42, "worker": {"paused": None, "active": "j2", "kind": "image"}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json=body))
    assert EngineClient(tmp_path).health() == EngineHealth(ready=True, active="j2", active_kind="image", uptime_ms=42)
