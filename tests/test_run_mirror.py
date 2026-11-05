"""Agent runs on the shared engine appear as rows, from manifests on disk."""

from __future__ import annotations

import json

import pytest

from fake_provider import FakeProvider
from src import config, projects
from src.config import Settings
from src.gen.models import JobStatus
from src.ui.generator.page import GeneratorPage
from src.web.run_mirror import RunMirror

URL = "https://flow.google.com/project/agent"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(config, "_settings", settings)
    yield projects.install(settings)
    projects.uninstall()


def write_run(data, jobs, url=URL, name="r1"):
    run = data / name
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(json.dumps({"id": name, "name": "a fox", "flowProjectUrl": url, "jobs": jobs}))
    registry = data / "runs.jsonl"
    line = json.dumps({"dir": str(run)}) + "\n"
    if line not in (registry.read_text() if registry.exists() else ""):
        with registry.open("a") as f:
            f.write(line)


def job(state="generating", kind="image", key=None, jid="j1", **data):
    return {"id": jid, "state": state, "idempotencyKey": key, "spec": {"prompt": "a fox", "kind": kind}, "data": data}


def test_agent_job_adds_exactly_one_row_in_a_project_made_for_its_url(store, tmp_path):
    write_run(tmp_path, [job()])
    mirror = RunMirror(tmp_path)
    mirror.start(store)
    mirror.refresh()
    project = next(p for p in store.list() if p.flow_url == URL)
    rows = project.rows("flow_image")
    assert len(rows) == 1 and rows[0]["origin"] == "agent" and rows[0]["prompt"] == "a fox"
    assert len(store.list()) == 2  # a second look makes no second project


def test_video_goes_to_the_video_page_in_the_matching_project(store, tmp_path):
    store.active.set_flow(URL, "")
    write_run(tmp_path, [job(kind="video")])
    RunMirror(tmp_path).start(store)
    assert len(store.active.rows("flow_video")) == 1 and store.active.rows("flow_image") == []


def test_an_app_started_job_isnt_mirrored_twice(store, tmp_path):
    store.active.set_flow(URL, "")
    write_run(tmp_path, [job(key="app:123"), job(key="prod:x", jid="j2")])
    RunMirror(tmp_path).start(store)
    assert store.active.rows("flow_image") == []


def test_rows_update_through_done(store, tmp_path):
    store.active.set_flow(URL, "")
    write_run(tmp_path, [job()])
    mirror = RunMirror(tmp_path)
    mirror.start(store)
    write_run(tmp_path, [job("done", outputs=[{"file": "a.jpg"}])])
    assert mirror.refresh() == 1 and mirror.refresh() == 0
    row = store.active.rows("flow_image")[0]
    assert row["status"] == "done" and row["outputs"] == ["a.jpg"]


def test_closed_app_run_shows_after_reopening(store, tmp_path):
    store.active.set_flow(URL, "")
    write_run(tmp_path, [job("done", outputs=[{"file": "a.jpg"}])])
    RunMirror(tmp_path).start(store)  # nothing was following when it ran
    page = GeneratorPage("flow_image", FakeProvider())
    assert page.jobs[0].status is JobStatus.DONE and page.jobs[0].origin == "agent"
    page.shutdown()


def test_live_page_gets_the_row(qapp, store, tmp_path):
    store.active.set_flow(URL, "")
    page = GeneratorPage("flow_image", FakeProvider())
    write_run(tmp_path, [job()])
    mirror = RunMirror(tmp_path, page_lookup=lambda project, key: page if key == "flow_image" else None)
    mirror.start(store)
    mirror.refresh()
    assert len(page.jobs) == 1 and page.jobs[0].status is JobStatus.RUNNING
    page.shutdown()


@pytest.mark.parametrize("state", ["done", "failed", "cancelled"])
def test_row_start_on_an_agent_row_doesnt_resubmit(qapp, store, tmp_path, state):
    store.active.set_flow(URL, "")
    write_run(tmp_path, [job(state)])
    RunMirror(tmp_path).start(store)
    page = GeneratorPage("flow_image", FakeProvider())
    assert page.start() == 0 and page.retry_failed() == 0 and page.retry_rows([0]) == 0
    page.shutdown()
