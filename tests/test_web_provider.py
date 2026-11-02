"""web_flow_image provider and queue behaviour with a fake engine backend (no browser)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.config import Settings
from src.gen.models import Job, JobStatus
from src.gen.output import save_outputs
from src.gen.provider import ProviderError, RunContext
from src.gen.queue import JobQueue, QueueSettings
from src.gen.web_flow_image import WebFlowImageProvider
from src.web.engine_client import EngineError, EngineToolError

JPG = b"\xff\xd8\xff\xe0fake-jpeg"


class FakeSession:
    def __init__(self):
        self.fronted = 0

    def bring_to_front(self, site):
        self.fronted += 1


class FakeBackend:
    """Stands in for FlowMcp: writes ``count`` files, or fails as the prompt asks.

    ``[code:XYZ]`` in the prompt raises an engine tool error with that code.
    """

    def __init__(self, root):
        self.root = root
        self.calls: list[dict] = []

    def run_job(self, tool, args, timeout, on_event=None, should_stop=None, **extra):
        self.calls.append(dict(args))
        prompt = args["prompt"]
        if "[code:" in prompt:
            code = prompt.split("[code:")[1].split("]")[0]
            raise EngineToolError(f"fake {code}", {"error_code": code, "retryable": code == "JOB_IN_PROGRESS"})
        if "[engine-down]" in prompt:
            raise EngineError("engine exited")
        if "[slow]" in prompt:
            raise TimeoutError("still running")
        outputs = []
        for i in range(0 if "[empty]" in prompt else args.get("count", 1)):
            f = self.root / f"{len(self.calls)}_{i}.jpg"
            f.write_bytes(JPG)
            outputs.append({"file": str(f), "mediaId": "m", "model": "banana21", "quotedCredits": 0})
        return {"state": "done", "outputs": outputs}


@pytest.fixture
def store(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.set("web.diag_dir", str(tmp_path / "diag"))
    return s


def make_provider(store, tmp_path):
    backend, session = FakeBackend(tmp_path), FakeSession()
    provider = WebFlowImageProvider(backend=backend, session=session)
    return provider, backend, session


def ctx():
    return RunContext(progress=lambda p: None, should_stop=lambda: False)


def test_generate_passes_options_and_reads_files(store, tmp_path):
    provider, backend, _ = make_provider(store, tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    job = Job("a red fox", refs=[ref])
    files = provider.generate(job, {"count": 2, "model": "bananaPro", "aspect": "16:9",
                                    "download_size": "2K", "timeout": 120}, ctx())
    assert [f.ext for f in files] == ["jpg", "jpg"] and files[0].data == JPG
    call = backend.calls[0]
    assert call["prompt"] == "a red fox" and call["model"] == "bananaPro"
    assert call["ratio"] == "16:9" and call["count"] == 2 and call["size"] == "2K"
    assert call["ingredients"] == [str(ref.resolve())]
    assert "output_folder" not in call  # the engine's run folder is the permanent one
    assert call["idempotency_key"].startswith("app:") and job.engine_key == ""


def test_count_is_clamped_and_no_refs_key_without_refs(store, tmp_path):
    provider, backend, _ = make_provider(store, tmp_path)
    provider.generate(Job("x"), {"count": 8}, ctx())
    assert backend.calls[0]["count"] == 4 and "ingredients" not in backend.calls[0]


def test_timeout_keeps_the_key_so_a_retry_spends_nothing(store, tmp_path):
    provider, backend, _ = make_provider(store, tmp_path)
    job = Job("x [slow]")
    with pytest.raises(ProviderError) as err:
        provider.generate(job, {}, ctx())
    assert err.value.retryable and job.engine_key == backend.calls[0]["idempotency_key"]
    with pytest.raises(ProviderError):
        provider.generate(job, {}, ctx())
    assert backend.calls[1]["idempotency_key"] == backend.calls[0]["idempotency_key"]


def test_progress_events_drive_the_row(store, tmp_path):
    from src.gen.web_flow_image import report_event

    seen, sources, previews = [], [], []
    c = RunContext(progress=seen.append, should_stop=lambda: False, partial=previews.append, note=sources.append)
    report_event({"type": "job.progress", "progress": 40, "source": "flow"}, c)
    report_event({"type": "job.progress", "progress": 40, "source": "flow", "previewPath": "p.png"}, c)
    report_event({"type": "job.transition", "state": "downloading"}, c)
    assert seen == [0.4, 0.4] and previews == [Path("p.png")] and sources[-1] == "phase"


@pytest.mark.parametrize("code,needle", [
    ("NOT_LOGGED_IN", "sign in"),
    ("WRONG_GOOGLE_ACCOUNT", "sign in"),
    ("MANUAL_VERIFICATION_REQUIRED", "CAPTCHA"),
    ("GOOGLE_LIMIT_REACHED", "limit"),
    ("WAF_BLOCK", "CAPTCHA"),
    ("DAILY_MODEL_LIMIT", "limit"),
])
def test_blocks_stop_queue_and_bring_window_up(store, tmp_path, code, needle):
    provider, _, session = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job(f"x [code:{code}]"), {}, ctx())
    assert err.value.stop_queue and not err.value.retryable
    assert needle in str(err.value)
    assert session.fronted == 1


@pytest.mark.parametrize("code", ["UNKNOWN_UI_CHANGE", "MODEL_NOT_AVAILABLE", "RATIO_NOT_AVAILABLE",
                                  "INVALID_PARAMS", "GENERATION_BUTTON_DISABLED"])
def test_setup_errors_stop_queue(store, tmp_path, code):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job(f"x [code:{code}]"), {}, ctx())
    assert err.value.stop_queue and code in str(err.value)


def test_refused_prompt_fails_only_that_job(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [code:GENERATION_REFUSED]"), {}, ctx())
    assert not err.value.stop_queue and not err.value.retryable


def test_only_what_the_engine_calls_safe_is_retried(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [code:JOB_IN_PROGRESS]"), {}, ctx())
    assert err.value.retryable and not err.value.stop_queue
    for prompt in ("x [code:FLOW_GENERATION_FAILED]", "x [code:DOWNLOAD_FAILED]", "x [empty]"):
        with pytest.raises(ProviderError) as err:  # past the credit line: another try spends
            provider.generate(Job(prompt), {}, ctx())
        assert not err.value.retryable


def test_engine_down_stops_queue(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [engine-down]"), {}, ctx())
    assert err.value.stop_queue and "engine" in str(err.value)


def test_daily_cap_stops_the_queue(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [code:DAILY_CAP_REACHED]"), {}, ctx())
    assert err.value.stop_queue


def test_queue_stops_batch_on_login_wall(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    done = threading.Event()
    q = JobQueue(provider, lambda job, files: save_outputs(job, files, tmp_path), on_finished=done.set)
    jobs = [Job("p [code:NOT_LOGGED_IN]", index=1)] + [Job(f"p{i}", index=i) for i in range(2, 5)]
    q.start(jobs, {}, QueueSettings(threads=1, max_retries=3))
    assert q.wait(10) and done.wait(2)
    assert jobs[0].status is JobStatus.FAILED and jobs[0].attempts == 1
    assert all(j.status is JobStatus.STOPPED for j in jobs[1:])


def test_queue_saves_flow_images(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    q = JobQueue(provider, lambda job, files: save_outputs(job, files, tmp_path / "saved"))
    jobs = [Job("a", index=1), Job("b", index=2)]
    q.start(jobs, {"count": 2}, QueueSettings(threads=2))
    assert q.wait(10)
    assert all(j.status is JobStatus.DONE and len(j.outputs) == 2 for j in jobs)
    assert jobs[0].outputs[0].read_bytes() == JPG


def test_image_page_provider_picker(qapp, store, tmp_path):
    from fake_provider import FakeProvider
    from src.ui.generator.page import GeneratorPage

    flow, _, _ = make_provider(store, tmp_path)
    store.set("pages.pick.save_dir", str(tmp_path / "out"))
    page = GeneratorPage("pick", FakeProvider(step_seconds=0), store=store, banner="api",
                         alternatives=[(flow, "web banner")])
    assert page.provider_combo is not None and page.provider.key == "fake"
    assert page.set_provider("web_flow_image")
    assert page.queue.provider is flow and page.banner_label.text() == "web banner"
    assert "download_size" in page.config_panel.fields and "model" in page.config_panel.fields
    assert store.get("pages.pick.provider") == "web_flow_image"
    # The choice is remembered for the next time the page is built.
    again = GeneratorPage("pick", FakeProvider(step_seconds=0), store=store,
                          alternatives=[(flow, "web banner")])
    assert again.provider is flow
    page.add_prompts(["a", "b"])
    assert page.start() == 2
    assert page.queue.wait(10)
    assert all(j.status is JobStatus.DONE for j in page.jobs)


def test_web_sessions_tab(qapp, store, tmp_path):
    import json

    from src.ui.pages.web_sessions_tab import WebSessionsTab

    class StatusSession(FakeSession):
        def login_state(self, site, open_flow=False):
            return "login"

        def open_site(self, site):
            self.opened = site
            return "ok"

    store.set("web.caps.flow", 5)
    (tmp_path / "flow-mcp").mkdir()
    from datetime import date
    (tmp_path / "flow-mcp" / "pacer.json").write_text(json.dumps({"day": date.today().isoformat(), "uses": 1}))
    tab = WebSessionsTab(store=store, session=StatusSession())
    row = tab.rows["flow"]
    assert row.usage.text() == "1 / 5" and row.cap.value() == 5
    row.cap.setValue(9)
    assert store.get("web.caps.flow") == 9
    assert tab.do_action("flow", "check") == "login"
    assert tab.do_action("flow", "launch") == "ok" and tab.session.opened == "flow"
    tab._on_done("flow", "check", "ok")
    assert "Signed in" in row.status.text()
    tab._on_done("flow", "launch", RuntimeError("Chrome not found"))
    assert "Chrome not found" in row.status.text()


def test_login_state_and_front_are_engine_calls():
    from src.web.session import BrowserSession

    class Backend:
        def __init__(self):
            self.calls = []
            self.reply = {"status": "connected", "accountStatus": "ok"}

        def call_tool(self, tool, args, timeout):
            self.calls.append((tool, args))
            return self.reply

    backend = Backend()
    session = BrowserSession(backend)
    assert session.login_state() == "ok"
    backend.reply = {"status": "oauth_required"}
    assert session.open_site() == "login"
    assert backend.calls == [("flow_connect", {"open_flow": False}), ("flow_connect", {"open_flow": True}),
                             ("flow_bring_to_front", {})]
