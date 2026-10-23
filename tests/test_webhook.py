"""Phase 10: webhook API (local HTTP on an ephemeral port) and stats counting.

No external network: every request goes to 127.0.0.1 on a port the OS picks.
Requests run on a helper thread while the test pumps Qt events, because the
backend hands page work to the GUI thread.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from PIL import Image

from src.characters.store import CharacterStore
from src.config import Settings
from src.gen.fake_provider import FakeProvider
from src.gen.models import Job, JobStatus
from src.gen.queue import JobQueue, add_finish_hook, remove_finish_hook
from src.stats.store import StatsStore
from src.ui.generator.page import GeneratorPage
from src.webhook.server import ApiError, WebhookServer, parse_submit


def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def http(method, url, body=None, token=None):
    """(status, json) for one request; never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def http_in_thread(qapp, *args, **kw):
    """Run ``http`` on a thread and pump events until it answers."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("r", http(*args, **kw)), daemon=True)
    t.start()
    assert run_until(qapp, lambda: "r" in box, timeout=15)
    return box["r"]


@pytest.fixture
def stats(tmp_path):
    store = StatsStore(tmp_path / "stats.json")
    add_finish_hook(store.on_job_finished)
    yield store
    remove_finish_hook(store.on_job_finished)


@pytest.fixture
def setup(qapp, tmp_path, stats):
    """A demo GeneratorPage on the fake provider plus a WebhookPage pointing at it."""
    from src.ui.webhook.page import WebhookPage

    store = Settings(tmp_path / "settings.json")
    store.set("pages.demo.save_dir", str(tmp_path / "out"))
    store.set("pages.demo.subdir_mode", "batch")
    chars = CharacterStore(tmp_path / "chars")
    demo = GeneratorPage("demo", FakeProvider(step_seconds=0.01, steps=3), store=store, characters=chars)
    pages = {"demo": demo}
    switched = []
    wh = WebhookPage(lambda key: pages[key], switched.append, store=store, stats=stats)
    yield wh, demo, store, switched
    wh.shutdown()
    demo.shutdown()


# ---- request parsing ------------------------------------------------
def test_parse_submit_normalises_and_validates():
    req = parse_submit({"page": "demo", "prompt": "  a fox  "})
    assert req == {"page": "demo", "prompts": ["a fox"], "refs": [], "character": "", "start": True,
                   "characters": [], "scenes": [], "project": ""}
    assert parse_submit({"page": "x", "prompts": ["a", "b"], "start": False})["prompts"] == ["a", "b"]
    for bad in ([], {"prompt": "a"}, {"page": "x"}, {"page": "x", "prompts": []},
                {"page": "x", "prompts": ["", "a"]}, {"page": "x", "prompt": 3},
                {"page": "x", "prompt": "a", "refs": "f.png"}, {"page": "x", "prompt": "a", "start": "yes"}):
        with pytest.raises(ApiError) as exc:
            parse_submit(bad)
        assert exc.value.status == 400


# ---- server without Qt ----------------------------------------------
class DummyBackend:
    def __init__(self):
        self.submitted = []

    def pages(self):
        return [{"key": "demo"}]

    def submit(self, req):
        self.submitted.append(req)
        return {"page": req["page"], "jobs": [{"id": 1}], "started": True}

    def job(self, job_id):
        return {"id": 1, "status": "done"} if job_id == 1 else None

    def jobs(self, page=None):
        return [{"id": 1, "page": "demo"}] if page in (None, "demo") else []

    def stats(self):
        return {"totals": {"jobs": 0}}


def test_server_routes_and_token():
    backend = DummyBackend()
    seen = []
    srv = WebhookServer(backend, port=0, token="s3cret", on_request=seen.append)
    srv.start()
    try:
        assert srv.port > 0 and srv.url == f"http://127.0.0.1:{srv.port}"
        base = srv.url
        # Token check: missing and wrong tokens are refused, both header styles work.
        assert http("GET", base + "/api/health")[0] == 401
        assert http("GET", base + "/api/health", token="nope")[0] == 401
        assert http("POST", base + "/api/jobs", {"page": "demo", "prompt": "x"})[0] == 401
        assert backend.submitted == []
        status, body = http("GET", base + "/api/health", token="s3cret")
        assert status == 200 and body["token_required"] is True
        req = urllib.request.Request(base + "/api/pages", headers={"X-Api-Token": "s3cret"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert json.loads(resp.read()) == {"pages": [{"key": "demo"}]}

        assert http("POST", base + "/api/jobs", {"page": "demo", "prompt": "fox"}, "s3cret")[0] == 202
        assert backend.submitted[0]["prompts"] == ["fox"]
        assert http("GET", base + "/api/jobs/1", token="s3cret") == (200, {"id": 1, "status": "done"})
        assert http("GET", base + "/api/jobs/2", token="s3cret")[0] == 404
        assert http("GET", base + "/api/jobs/abc", token="s3cret")[0] == 400
        assert http("GET", base + "/api/jobs?page=other", token="s3cret") == (200, {"jobs": []})
        assert http("GET", base + "/nope", token="s3cret")[0] == 404
        assert http("DELETE", base + "/api/jobs/1", token="s3cret")[0] == 405
        assert http("POST", base + "/api/jobs", {"page": "demo"}, "s3cret")[0] == 400

        raw = urllib.request.Request(base + "/api/jobs", data=b"{not json", method="POST",
                                     headers={"Authorization": "Bearer s3cret"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(raw, timeout=5)
        assert err.value.code == 400
        assert seen and seen[0].status == 401
    finally:
        srv.stop()
    assert not srv.running


def test_server_without_token_and_busy_port():
    srv = WebhookServer(DummyBackend(), port=0)
    srv.start()
    try:
        assert http("GET", srv.url + "/api/health")[1]["token_required"] is False
        clash = WebhookServer(DummyBackend(), port=srv.port)
        with pytest.raises(OSError):
            clash.start()
    finally:
        srv.stop()


# ---- end to end: HTTP -> GUI queue -> fake provider ----------------
def test_submit_over_http_runs_through_queue(qapp, setup, stats, tmp_path):
    wh, demo, _, _ = setup
    assert wh.start_server(port=0)
    base = wh.url
    assert wh.btn_toggle.text() == "Stop server" and base in wh.status.text()
    assert "/api/jobs" in wh.example.toPlainText()

    status, body = http_in_thread(qapp, "GET", base + "/api/pages")
    assert status == 200 and body["pages"][0]["key"] == "demo" and body["pages"][0]["provider"] == "fake"

    status, body = http_in_thread(qapp, "POST", base + "/api/jobs",
                                  {"page": "demo", "prompts": ["a red fox", "an [fail] owl"]})
    assert status == 202 and body["started"] is True
    ids = [j["id"] for j in body["jobs"]]
    assert len(ids) == 2 and [j.prompt for j in demo.jobs] == ["a red fox", "an [fail] owl"]

    assert run_until(qapp, lambda: not demo.queue.is_running()
                     and all(j.status in (JobStatus.DONE, JobStatus.FAILED) for j in demo.jobs))

    status, info = http_in_thread(qapp, "GET", f"{base}/api/jobs/{ids[0]}")
    assert status == 200 and info["status"] == "done" and info["progress"] == 1.0
    assert info["outputs"] and all((tmp_path / "out") in __import__("pathlib").Path(p).parents
                                   for p in info["outputs"])
    status, info = http_in_thread(qapp, "GET", f"{base}/api/jobs/{ids[1]}")
    assert info["status"] == "failed" and info["error"]
    status, listing = http_in_thread(qapp, "GET", base + "/api/jobs?page=demo")
    assert [j["id"] for j in listing["jobs"]] == ids

    # Stats: counted by the queue hook, visible over the API and in the Stats tab.
    status, snap = http_in_thread(qapp, "GET", base + "/api/stats")
    fake = next(r for r in snap["providers"] if r["key"] == "fake")
    assert (fake["jobs"], fake["done"], fake["failed"]) == (2, 1, 1)
    assert fake["outputs"] == len(demo.jobs[0].outputs) >= 1
    assert run_until(qapp, lambda: wh.stats_view.table.rowCount() == 2)  # provider + total
    assert wh.stats_view.value("fake", "done") == 1
    assert wh.stats_view.table.item(0, 1).text() == "2"
    assert wh.stats_view.table.item(1, 0).text() == "Total"
    assert any("submitted to demo" in wh.requests.item(i).text() for i in range(wh.requests.count()))

    # A second submit while idle starts again; start=false only queues the row.
    status, body = http_in_thread(qapp, "POST", base + "/api/jobs",
                                  {"page": "demo", "prompt": "later", "start": False})
    assert status == 202 and body["started"] is False and demo.jobs[-1].status is JobStatus.PENDING

    status, body = http_in_thread(qapp, "POST", base + "/api/jobs", {"page": "nope", "prompt": "x"})
    assert status == 404 and "demo" in body["error"]
    wh.stop_server()
    assert not wh.running and wh.btn_toggle.text() == "Start server"


def test_submit_while_running_joins_the_batch(qapp, setup):
    wh, demo, _, _ = setup
    demo.provider.step_seconds = 0.05
    assert wh.start_server(port=0)
    _, first = http_in_thread(qapp, "POST", wh.url + "/api/jobs", {"page": "demo", "prompt": "one"})
    assert demo.queue.is_running()
    status, second = http_in_thread(qapp, "POST", wh.url + "/api/jobs", {"page": "demo", "prompt": "two"})
    assert status == 202 and second["started"] is True
    assert run_until(qapp, lambda: all(j.status is JobStatus.DONE for j in demo.jobs))


def test_page_token_refs_and_character(qapp, setup, tmp_path):
    wh, demo, store, switched = setup
    wh.token.setText("tok-123")
    assert store.get("webhook.token") == "tok-123"
    assert wh.start_server(port=0)
    assert not wh.token.isEnabled()
    assert 'Authorization: Bearer tok-123' in wh.example.toPlainText()

    assert http_in_thread(qapp, "POST", wh.url + "/api/jobs", {"page": "demo", "prompt": "x"})[0] == 401
    assert demo.jobs == []

    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8), "red").save(ref)
    demo.characters.add("Mara", images=[ref])
    status, body = http_in_thread(qapp, "POST", wh.url + "/api/jobs",
                                  {"page": "demo", "prompt": "Mara waves", "refs": [str(ref)],
                                   "character": "mara", "start": False}, token="tok-123")
    assert status == 202
    job = demo.jobs[0]
    assert job.character and len(job.refs) == 2 and ref in job.refs

    status, body = http_in_thread(qapp, "POST", wh.url + "/api/jobs",
                                  {"page": "demo", "prompt": "y", "character": "Nobody"}, token="tok-123")
    assert status == 400 and "Nobody" in body["error"]
    status, body = http_in_thread(qapp, "POST", wh.url + "/api/jobs",
                                  {"page": "demo", "prompt": "y", "refs": [str(tmp_path / "missing.png")]},
                                  token="tok-123")
    assert status == 400 and "not found" in body["error"]

    wh.btn_demo.click()
    assert switched == ["demo"]


def test_lan_mode_needs_token(qapp, setup):
    wh, _, store, _ = setup
    wh.lan.setChecked(True)
    assert store.get("webhook.lan") is True
    assert not wh.start_server(port=0)
    assert not wh.running and "token" in wh.status.text().lower()


def test_port_in_use_is_reported(qapp, setup):
    wh, _, _, _ = setup
    other = WebhookServer(DummyBackend(), port=0)
    other.start()
    try:
        wh.port.setValue(other.port)
        assert not wh.start_server()
        assert "Could not start" in wh.status.text()
    finally:
        other.stop()


# ---- stats store ------------------------------------------------------
def test_stats_store_counts_persists_and_resets(tmp_path):
    path = tmp_path / "stats.json"
    s = StatsStore(path)
    changes = []
    s.subscribe(lambda: changes.append(1))
    s.record("gemini", "Gemini", JobStatus.DONE, 2)
    s.record("gemini", "Gemini", JobStatus.FAILED)
    s.record("openai", "OpenAI", JobStatus.STOPPED)
    assert len(changes) == 3 and s.since

    again = StatsStore(path)
    rows = {r["key"]: r for r in again.rows()}
    assert rows["gemini"] == {"key": "gemini", "name": "Gemini", "jobs": 2, "done": 1,
                              "failed": 1, "stopped": 0, "outputs": 2}
    assert again.totals() == {"jobs": 3, "done": 1, "failed": 1, "stopped": 1, "outputs": 2}
    again.reset()
    assert StatsStore(path).rows() == [] and StatsStore(path).since == ""


def test_queue_hook_counts_each_finished_job(tmp_path):
    store = StatsStore(tmp_path / "stats.json")
    add_finish_hook(store.on_job_finished)
    add_finish_hook(store.on_job_finished)  # registering twice is a no-op
    try:
        provider = FakeProvider(step_seconds=0.0, steps=2)
        q = JobQueue(provider, lambda job, files: [tmp_path / f"{job.id}_{i}.png" for i, _ in enumerate(files)])
        jobs = [Job("ok", index=1), Job("[fail]", index=2), Job("[flaky] once", index=3)]
        q.start(jobs, {"count": 2})
        assert q.wait(10)
        row = store.rows()[0]
        # The flaky job's retryable failure is re-queued, not counted; it then succeeds.
        assert (row["key"], row["jobs"], row["done"], row["failed"], row["outputs"]) == ("fake", 3, 2, 1, 4)
    finally:
        remove_finish_hook(store.on_job_finished)


def test_main_window_registers_webhook_and_demo(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow
    from src.ui.webhook.page import WebhookPage

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    monkeypatch.setattr("src.stats.store._default", StatsStore(tmp_path / "stats.json"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("webhook")
    page = window.page("webhook")
    assert isinstance(page, WebhookPage) and not page.running
    assert isinstance(window.page("demo"), GeneratorPage)
    page.btn_demo.click()
    assert window.current_key == "demo"
    window.close()
