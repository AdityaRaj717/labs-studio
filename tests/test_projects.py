"""Phase 12: project store, migration, per-project settings/rows/outputs, switching,
the webhook ``project`` field and one Flow project per app project."""

from __future__ import annotations

import json
import time

import pytest

from src import projects
from src.config import Settings
from fake_provider import FakeProvider
from src.gen.models import Job, JobStatus
from src.gen.output import default_save_dir
from src.projects import ProjectBusyError, ProjectStore
from src.projects.store import OLD_MCP_DIR, job_to_row, row_to_job
from src.ui.generator.page import GeneratorPage


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "LabsStudio"


@pytest.fixture
def installed(appdata, tmp_path):
    settings = Settings(tmp_path / "settings.json")
    settings.set("web.flow_mcp_dir", str(tmp_path / "no-mcp"))  # don't read the real old MCP's projects
    store = projects.install(settings)
    yield settings, store
    projects.uninstall()


def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---- store -------------------------------------------------------------
def test_migration_makes_default_from_old_settings(appdata, tmp_path):
    mcp = tmp_path / "oldmcp"
    (mcp / "config").mkdir(parents=True)
    (mcp / "config" / "flow.projects.json").write_text(json.dumps({"projects": [
        {"url": "https://flow.google.com/project/abc", "campaign": "labs-studio"}]}))
    settings = Settings(tmp_path / "settings.json")
    settings.set("pages.flow_image.model", "Pro")
    settings.set("web.flow_mcp_dir", str(mcp))
    store = ProjectStore(settings)
    store.load()
    default = store.active
    assert default.id == "default" and default.name == "Default"
    assert default.get("pages.flow_image.model") == "Pro"
    assert default.output_dir == appdata / "outputs"  # old outputs stay where they were
    assert default.flow_url == "https://flow.google.com/project/abc"
    assert settings.get("projects.active") == "default"
    # loads again without migrating twice
    store2 = ProjectStore(settings)
    store2.load()
    assert list(store2.projects) == ["default"]


def test_old_mcp_dir_means_repo_copy(tmp_path):
    from src.web.flow_mcp import BUNDLED_MCP_DIR, FlowMcp

    settings = Settings(tmp_path / "settings.json")
    settings.set("web.flow_mcp_dir", OLD_MCP_DIR)
    assert FlowMcp(store=settings).mcp_dir == BUNDLED_MCP_DIR


def test_create_rename_duplicate_delete(installed):
    settings, store = installed
    settings.set("pages.flow_video.count", 3)  # routed to Default
    a = store.create("Cats")
    b = store.create("Dogs", settings_from="default")
    assert a.output_dir == store.projects_dir / a.id / "outputs"
    assert a.get("pages.flow_video.count") is None and b.get("pages.flow_video.count") == 3
    with pytest.raises(ValueError):
        store.create("cats")
    with pytest.raises(ValueError):
        store.rename(b.id, "CATS")
    store.rename(b.id, "Wolves")
    assert store.find("wolves") is b and store.find(b.id) is b

    store.activate(a.id)
    (a.output_dir).mkdir(parents=True)
    (a.output_dir / "x.png").write_bytes(b"x")
    store.delete(a.id)  # keep files
    assert store.active.id != a.id and a.id not in store.projects
    assert (a.output_dir / "x.png").exists() and (a.folder / "project.deleted.json").exists()
    store.delete(b.id, delete_files=True)
    assert not b.folder.exists()
    with pytest.raises(ValueError):
        store.delete("default")  # the last one


def test_settings_route_pages_to_active_project(installed):
    settings, store = installed
    settings.set("pages.flow_image.aspect", "16:9")
    other = store.create("Other")
    store.activate(other.id)
    assert settings.get("pages.flow_image.aspect", "1:1") == "1:1"
    settings.set("pages.flow_image.aspect", "9:16")
    store.activate("default")
    assert settings.get("pages.flow_image.aspect") == "16:9"
    assert "pages" not in json.loads(settings.path.read_text())  # never written to settings.json
    assert default_save_dir("flow_video") == store.active.output_dir / "flow_video"


def test_switch_refused_while_busy(installed):
    _, store = installed
    other = store.create("Other")
    store.busy_check = lambda: True
    with pytest.raises(ProjectBusyError):
        store.activate(other.id)
    assert store.active.id == "default"


def test_rows_round_trip():
    job = Job("a fox", status=JobStatus.RUNNING, character="c1")
    row = job_to_row(job)
    back = row_to_job(json.loads(json.dumps(row)), 1)
    assert back.prompt == "a fox" and back.status is JobStatus.STOPPED and back.character == "c1"


# ---- pages keep rows and settings per project across a restart ----------
def test_generator_rows_survive_restart_and_switch(qapp, installed, tmp_path):
    settings, store = installed
    page = GeneratorPage("demo", FakeProvider(step_seconds=0.01, steps=2))
    page.add_prompts(["one", "two"])
    page.config_panel.set_value("delay_min", 0.0)
    page.config_panel.set_value("delay_max", 0.0)
    assert page.start() == 2
    assert run_until(qapp, lambda: not page.queue.is_running() and all(
        j.status is JobStatus.DONE for j in page.jobs))
    page.shutdown()
    outs = page.jobs[0].outputs
    assert outs and outs[0].is_relative_to(store.active.output_dir / "demo")

    other = store.create("Other")
    store.activate(other.id)
    page2 = GeneratorPage("demo", FakeProvider())
    assert page2.jobs == []
    page2.add_prompts(["three"])
    page2.shutdown()

    # "restart": a fresh store from the same files
    projects.uninstall()
    store = projects.install(Settings(settings.path))
    assert store.active.id == other.id
    assert [j.prompt for j in GeneratorPage("demo", FakeProvider()).jobs] == ["three"]
    store.activate("default")
    restored = GeneratorPage("demo", FakeProvider()).jobs
    assert [j.prompt for j in restored] == ["one", "two"]
    assert restored[0].status is JobStatus.DONE and restored[0].outputs == outs


def test_main_window_switch_rebuilds_project_pages(qapp, installed, monkeypatch, tmp_path):
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow

    settings, store = installed
    monkeypatch.setattr(config, "_settings", settings)
    monkeypatch.setattr("src.stats.store._default", None, raising=False)
    window = MainWindow()
    window.attach_projects(store)
    register_pages(window)
    window.register_page("flow_image", lambda: GeneratorPage("flow_image", FakeProvider()))
    window.switch_page("flow_image")
    demo = window.page("flow_image")
    demo.add_prompts(["kept in Default"])
    other = store.create("Other")
    window.picker.refresh()
    assert window.picker.combo.count() == 2
    store.activate(other.id)
    assert window.page("flow_image") is not demo and window.page("flow_image").jobs == []
    assert "Other" in window.windowTitle()
    store.activate("default")
    assert [j.prompt for j in window.page("flow_image").jobs] == ["kept in Default"]
    window.switch_page("projects")
    assert window.page("projects").table.rowCount() == 2
    window.close()


# ---- webhook ------------------------------------------------------------
def test_webhook_project_field(qapp, installed, tmp_path):
    from src.ui.webhook.backend import PageBackend
    from src.webhook.server import ApiError, parse_submit

    _, store = installed
    other = store.create("Other")
    pages: dict = {}

    def lookup(key):
        if key not in pages or pages[key][0] is not store.active:
            pages[key] = (store.active, GeneratorPage(key, FakeProvider()))
        return pages[key][1]

    backend = PageBackend(lookup, page_keys=("demo",))
    res = backend.submit(parse_submit({"page": "demo", "prompt": "p1", "start": False, "project": "other"}))
    assert res["project"] == "Other" and store.active is other
    assert [j.prompt for j in lookup("demo").jobs] == ["p1"]
    res = backend.submit(parse_submit({"page": "demo", "prompt": "p2", "start": False}))
    assert res["project"] == "Other"  # default: the active project
    with pytest.raises(ApiError) as err:
        backend.submit(parse_submit({"page": "demo", "prompt": "x", "project": "nope"}))
    assert err.value.status == 404
    store.busy_check = lambda: True
    with pytest.raises(ApiError) as err:
        backend.submit(parse_submit({"page": "demo", "prompt": "x", "project": "Default"}))
    assert err.value.status == 409
    for _, page in pages.values():
        page.shutdown()


# ---- Flow project per app project --------------------------------------
def test_flow_project_created_once_and_used_for_jobs(installed, tmp_path):
    from tests.test_mcp_client import make_flow

    _, store = installed
    flow, clients, _ = make_flow(tmp_path)
    flow.generate_image({"prompt": "a"}, timeout=60)
    flow.generate_image({"prompt": "b"}, timeout=60)
    calls = clients[0].calls
    assert [n for n, _ in calls] == ["flow_connect", "flow_open_project", "flow_generate_image",
                                     "flow_generate_image"]
    assert calls[1][1] == {"name": "Default", "create_if_missing": True}
    url = store.active.flow_url
    assert url.startswith("https://flow.google.com/project/") and calls[2][1]["project_url"] == url
    assert json.loads(store.active.file.read_text())["flow"]["url"] == url

    other = store.create("Other")
    store.activate(other.id)
    flow.ensure_project(other)
    assert other.flow_url and other.flow_url != url
    # back to Default: opens the stored URL, no new project
    store.activate("default")
    flow.ensure_project(store.active)
    assert clients[0].calls[-1][1] == {"name": "Default", "create_if_missing": True, "url": url}


def test_flow_project_gone_is_recreated(installed, tmp_path):
    from tests.test_mcp_client import make_flow

    _, store = installed
    flow, clients, _ = make_flow(tmp_path)
    flow.ensure_project(store.active)
    clients[0].fail_next = ["PROJECT_NOT_FOUND"]  # deleted in Flow after it was opened
    assert flow.generate_image({"prompt": "a"}, timeout=60)["status"] == "success"
    names = [n for n, _ in clients[0].calls]
    assert names == ["flow_connect", "flow_open_project", "flow_generate_image", "flow_open_project",
                     "flow_generate_image"]


def test_flow_mcp_defaults_to_repo_copy_and_passes_env(tmp_path):
    from src.web.flow_mcp import BUNDLED_MCP_DIR, FlowMcp

    store = Settings(tmp_path / "s.json")
    store.set("web.port", 9444)
    flow = FlowMcp(store=store)
    assert flow.mcp_dir == BUNDLED_MCP_DIR and (BUNDLED_MCP_DIR / "src" / "index.js").is_file()
    env = flow.env()
    assert env["FLOW_CDP_PORT"] == "9444" and env["FLOW_DATA_DIR"].endswith("flow-mcp")
