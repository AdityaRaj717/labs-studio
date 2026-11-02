"""The app on the engine: a fake engine over real HTTP, and a stub client for ``FlowMcp``. No Node, no browser."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PySide6.QtCore import Qt

from src.config import Settings
from src.gen.models import Job, JobStatus
from src.gen.provider import StopRequested
from src.gen.queue import JobQueue, QueueSettings
from src.ui.generator.prompt_model import COL_OUTPUT, COL_PROGRESS, PromptTableModel
from src.web.engine_client import EngineClient, EngineError, EngineToolError, read_manifests, row_state, uses_today
from src.web.flow_mcp import FlowMcp

ROOT = Path(__file__).resolve().parents[1]


class FakeEngine:
    def __init__(self, data_dir: Path, version="1.0.0"):
        self.calls: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.drop_after: int | None = None  # close the first stream after this many events
        self.seen_since: list[int] = []
        engine = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                if self.headers.get("authorization") != "Bearer tok":
                    return self._json(401, {"ok": False})
                if url.path == "/health":
                    return self._json(200, {"ready": True, "seq": len(engine.events)})
                since = int(parse_qs(url.query).get("since", ["0"])[0])
                engine.seen_since.append(since)
                self.send_response(200)
                self.end_headers()
                out = engine.events[since:]
                if engine.drop_after is not None:
                    out, engine.drop_after = out[:engine.drop_after], None
                for event in out:
                    self.wfile.write(f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
                return None

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                engine.calls.append((body["tool"], body["args"]))
                if body["tool"] == "fail":
                    return self._json(200, {"ok": False, "error_code": "NOT_LOGGED_IN", "message": "sign in"})
                return self._json(200, {"ok": True, "result": {"echo": body["args"]}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "engine.json").write_text(json.dumps(
            {"pid": 1, "port": self.server.server_address[1], "token": "tok", "version": version}))

    def add(self, **event):
        self.events.append({"seq": len(self.events) + 1, **event})


@pytest.fixture
def engine(tmp_path):
    fake = FakeEngine(tmp_path)
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def test_call_returns_result_and_raises_tool_errors(engine, tmp_path):
    client = EngineClient(tmp_path)
    assert client.call("flow_status", {"a": 1}) == {"echo": {"a": 1}}
    with pytest.raises(EngineToolError) as err:
        client.call("fail")
    assert err.value.code == "NOT_LOGGED_IN" and str(err.value) == "sign in"


def test_found_engine_is_not_started_again(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("started a second engine"))
    assert EngineClient(tmp_path, ["node", "start.js"], version="1.0.0").ensure()["port"] == engine.server.server_address[1]


def test_no_engine_and_no_command_is_a_clear_error(tmp_path):
    with pytest.raises(EngineError):
        EngineClient(tmp_path).call("flow_status")


def test_sse_reconnect_replays_missed_events(engine, tmp_path):
    for n in range(4):
        engine.add(type="job.progress", jobId="j", progress=n)
    engine.drop_after = 2
    stop = threading.Event()
    got = []
    for event in EngineClient(tmp_path).events(0, stop):
        got.append(event["progress"])
        if len(got) == 4:
            stop.set()
    assert got == [0, 1, 2, 3]
    assert engine.seen_since[:2] == [0, 2]  # the second connection asked from the last one seen


# ---- FlowMcp over a stub client ------------------------------------------
class StubClient:
    """Answers like the engine; ``views`` are what successive flow_wait calls return."""

    def __init__(self, *a):
        self.calls: list[tuple[str, dict]] = []
        self.views = [{"finished": True, "state": "done", "outputs": []}]
        self.stream: list[dict] = []
        self.fail_queue: list[str] = []

    def head(self):
        return 0

    def events(self, since, stop):
        yield from self.stream
        stop.wait(5)

    def call(self, tool, args=None, timeout=60):
        self.calls.append((tool, args or {}))
        if tool.startswith("flow_generate"):
            if self.fail_queue:
                code = self.fail_queue.pop(0)
                raise EngineToolError(code, {"error_code": code})
            return {"job_id": "j1", "run_id": "r1"}
        if tool == "flow_wait":
            return self.views.pop(0) if len(self.views) > 1 else self.views[0]
        if tool == "flow_open_project":
            n = sum(1 for t, _ in self.calls if t == tool)
            return {"status": "success", "url": args.get("url") or f"https://flow.google.com/project/p{n}",
                    "created": not args.get("url"), "title": args["name"]}
        return {"status": "success", "characters": [], "name": args.get("name", "") if args else ""}


def make_flow(tmp_path):
    store = Settings(tmp_path / "s.json")
    store.set("web.flow_mcp_dir", str(tmp_path / "mcp"))
    store.set("web.node_path", "node.exe")
    clients: list[StubClient] = []

    def factory(*a):
        clients.append(StubClient(*a))
        return clients[-1]

    return FlowMcp(store=store, client_factory=factory), clients


def tools(client):
    return [t for t, _ in client.calls if t not in ("flow_set_pacing", "flow_wait")]


def test_starts_the_engine_script_and_pushes_pacing(tmp_path):
    flow, clients = make_flow(tmp_path)
    flow.store.set("web.gap_min", 30.0)
    flow.store.set("web.gap_max", 10.0)
    flow.store.set("web.caps.flow", 7)
    flow.run_job("flow_generate_image", {"prompt": "a"}, 60)
    assert flow.command() == ["node.exe", str(tmp_path / "mcp" / "src" / "engine" / "start.js")]
    assert dict(clients[0].calls)["flow_set_pacing"] == {"dailyCap": 7, "minGapMs": 10000, "maxGapMs": 30000}
    assert dict(clients[0].calls)["flow_generate_image"]["auto_confirm"] is True


def test_progress_event_reaches_the_caller(tmp_path):
    flow, clients = make_flow(tmp_path)
    client = flow.client
    client.stream = [{"type": "job.progress", "jobId": "other", "progress": 1},
                     {"type": "job.progress", "jobId": "j1", "progress": 40, "source": "flow"}]
    done, seen = threading.Event(), []
    client.views = [{"finished": False}] * 50 + [{"finished": True, "state": "done"}]

    def on_event(event):
        seen.append(event)
        done.set()
        client.views = [{"finished": True, "state": "done"}]

    flow.run_job("flow_generate_image", {"prompt": "a"}, 60, on_event=on_event)
    assert [e["progress"] for e in seen] == [40]


def test_failed_view_raises_with_the_engine_code(tmp_path):
    flow, _ = make_flow(tmp_path)
    flow.client.views = [{"finished": True, "state": "failed",
                          "error": {"error_code": "GENERATION_REFUSED", "message": "no"}}]
    with pytest.raises(EngineToolError) as err:
        flow.run_job("flow_generate_image", {"prompt": "a"}, 60)
    assert err.value.code == "GENERATION_REFUSED"


def test_paused_queue_does_not_spin(tmp_path):
    flow, _ = make_flow(tmp_path)
    flow.client.views = [{"finished": False, "queue_paused": {"reason": "GOOGLE_LIMIT_REACHED", "next_action": "wait"}}]
    with pytest.raises(EngineToolError) as err:
        flow.run_job("flow_generate_image", {"prompt": "a"}, 60)
    assert err.value.code == "GOOGLE_LIMIT_REACHED"


def test_stop_cancels_the_engine_job(tmp_path):
    flow, clients = make_flow(tmp_path)
    with pytest.raises(StopRequested):
        flow.run_job("flow_generate_image", {"prompt": "a"}, 60, should_stop=lambda: True)
    assert ("flow_job_control", {"action": "cancel", "job_id": "j1"}) in clients[0].calls


# ---- rows ----------------------------------------------------------------
def test_partial_sets_preview_then_outputs_replace_it(qapp, tmp_path):
    from PIL import Image

    from src.gen.models import OutputFile
    from src.gen.provider import Provider

    shot = tmp_path / "preview.png"
    Image.new("RGB", (8, 8), "red").save(shot)
    final = tmp_path / "final.png"
    Image.new("RGB", (8, 8), "blue").save(final)
    model = PromptTableModel()
    job = Job("a", index=1)
    model.jobs.append(job)
    seen = {}

    class Partial(Provider):
        def generate(self, job, options, ctx):
            ctx.note("flow")
            ctx.progress(0.4)
            ctx.partial(shot)
            seen["preview"] = job.preview
            seen["icon"] = model.data(model.index(0, COL_OUTPUT), Qt.ItemDataRole.DecorationRole)
            seen["tip"] = model.data(model.index(0, COL_PROGRESS), Qt.ItemDataRole.ToolTipRole)
            seen["progress"] = job.progress
            return [OutputFile(b"x", "png")]

    queue = JobQueue(Partial(), lambda j, files: [final])
    queue.start([job], {}, QueueSettings(threads=1))
    assert queue.wait(10)
    assert seen["preview"] == shot and seen["icon"] is not None and not seen["icon"].isNull()
    assert seen["progress"] == 0.4 and "40" in seen["tip"]
    assert job.preview is None and job.outputs == [final]
    assert not model.data(model.index(0, COL_OUTPUT), Qt.ItemDataRole.DecorationRole).isNull()


def test_phase_is_not_shown_as_flows_percent(qapp):
    model = PromptTableModel()
    job = Job("a", index=1, progress=0.05, progress_source="phase")
    model.jobs.append(job)
    tip = model.data(model.index(0, COL_PROGRESS), Qt.ItemDataRole.ToolTipRole)
    assert "5%" not in tip and "no percent" in tip


def test_app_restart_rebuilds_rows_from_manifests(tmp_path):
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    done = {"id": "a", "state": "done", "spec": {"prompt": "fox"},
            "data": {"outputs": [{"file": str(run / "images" / "a.jpg"), "mediaId": "m", "model": "banana21"}]}}
    failed = {"id": "b", "state": "failed", "spec": {"prompt": "owl"}, "data": {"error": {"message": "refused"}}}
    running = {"id": "c", "state": "generating", "spec": {"prompt": "elk"}, "data": {}}
    (run / "manifest.json").write_text(json.dumps({"id": "r1", "jobs": [done, failed, running]}))
    (tmp_path / "runs.jsonl").write_text(json.dumps({"dir": str(run)}) + "\n" + json.dumps({"dir": str(tmp_path / "gone")}) + "\n")
    runs = read_manifests(tmp_path)
    assert [r["id"] for r in runs] == ["r1"]
    states = [row_state(j) for j in runs[0]["jobs"]]
    assert states[0]["status"] is JobStatus.DONE and states[0]["outputs"] == [run / "images" / "a.jpg"]
    assert states[1]["status"] is JobStatus.FAILED and states[1]["error"] == "refused"
    assert states[2]["status"] is JobStatus.RUNNING


def test_usage_comes_from_the_engines_file(tmp_path):
    from datetime import date

    assert uses_today(tmp_path) == 0
    (tmp_path / "pacer.json").write_text(json.dumps({"day": date.today().isoformat(), "uses": 3}))
    assert uses_today(tmp_path) == 3
    (tmp_path / "pacer.json").write_text(json.dumps({"day": "2000-01-01", "uses": 3}))
    assert uses_today(tmp_path) == 0


def test_web_code_names_no_flow_host_or_other_profile():
    for path in (ROOT / "src" / "web").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "labs.google" not in text and "Profile 3" not in text, path
