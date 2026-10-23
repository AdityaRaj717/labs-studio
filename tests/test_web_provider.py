"""web_flow_image provider, pacing and queue behaviour with a fake MCP backend (no browser)."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest

from src.config import Settings
from src.gen.models import Job, JobStatus
from src.gen.output import save_outputs
from src.gen.provider import ProviderError, RunContext
from src.gen.queue import JobQueue, QueueSettings
from src.gen.web_flow_image import WebFlowImageProvider
from src.web.mcp_client import McpError, McpToolError
from src.web.pacing import Pacer

JPG = b"\xff\xd8\xff\xe0fake-jpeg"


class FakeSession:
    def __init__(self):
        self.fronted = 0

    def bring_to_front(self, site):
        self.fronted += 1


class FakeBackend:
    """Stands in for FlowMcp: writes ``count`` files, or fails as the prompt asks.

    ``[code:XYZ]`` in the prompt raises an MCP tool error with that code.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def generate_image(self, args, timeout):
        self.calls.append(dict(args))
        prompt = args["prompt"]
        if "[code:" in prompt:
            code = prompt.split("[code:")[1].split("]")[0]
            raise McpToolError(f"fake {code}", {"error": True, "error_code": code, "message": f"fake {code}"})
        if "[mcp-down]" in prompt:
            raise McpError("google-flow exited (code 1)")
        if "[running]" in prompt:
            return {"status": "running", "jobId": "x"}
        out = Path(args["output_folder"])
        out.mkdir(parents=True, exist_ok=True)
        files = []
        for i in range(0 if "[empty]" in prompt else args["count"]):
            f = out / f"img_v{i + 1}.jpg"
            f.write_bytes(JPG)
            files.append(str(f))
        return {"status": "success", "files": files, "agent_reply": "Here you go"}


@pytest.fixture
def store(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.set("web.gap_min", 0.0)
    s.set("web.gap_max", 0.0)
    s.set("web.caps.flow", 0)
    return s


def make_provider(store, tmp_path):
    backend, session = FakeBackend(), FakeSession()
    provider = WebFlowImageProvider(backend=backend, pacer=Pacer("flow", store), session=session,
                                    out_root=tmp_path / "mcp_out")
    return provider, backend, session


def ctx():
    return RunContext(progress=lambda p: None, should_stop=lambda: False)


def test_generate_passes_options_and_reads_files(store, tmp_path):
    provider, backend, _ = make_provider(store, tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    job = Job("a red fox", refs=[ref])
    files = provider.generate(job, {"count": 2, "model": "Nano Banana Pro", "aspect": "16:9",
                                    "download_size": "2K", "timeout": 120}, ctx())
    assert [f.ext for f in files] == ["jpg", "jpg"] and files[0].data == JPG
    call = backend.calls[0]
    assert call["prompt"] == "a red fox" and call["model"] == "Nano Banana Pro"
    assert call["ratio"] == "16:9" and call["count"] == 2 and call["download_size"] == "2K"
    assert call["reference_images"] == [str(ref.resolve())]
    assert not Path(call["output_folder"]).exists()  # temp folder cleaned up
    assert provider.pacer.used_today() == 1
    assert store.get("web.usage.flow")["date"] == date.today().isoformat()


def test_count_is_clamped_and_no_refs_key_without_refs(store, tmp_path):
    provider, backend, _ = make_provider(store, tmp_path)
    provider.generate(Job("x"), {"count": 8}, ctx())
    assert backend.calls[0]["count"] == 4 and "reference_images" not in backend.calls[0]


@pytest.mark.parametrize("code,needle", [
    ("NOT_LOGGED_IN", "sign in"),
    ("WRONG_GOOGLE_ACCOUNT", "sign in"),
    ("MANUAL_VERIFICATION_REQUIRED", "CAPTCHA"),
    ("GOOGLE_LIMIT_REACHED", "limit"),
])
def test_blocks_stop_queue_and_bring_window_up(store, tmp_path, code, needle):
    provider, _, session = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job(f"x [code:{code}]"), {}, ctx())
    assert err.value.stop_queue and not err.value.retryable
    assert needle in str(err.value)
    assert session.fronted == 1
    assert provider.pacer.used_today() == 0


@pytest.mark.parametrize("code", ["UNKNOWN_UI_CHANGE", "MODEL_NOT_AVAILABLE", "RATIO_NOT_AVAILABLE",
                                  "INVALID_PARAMS", "GENERATION_BUTTON_DISABLED"])
def test_setup_errors_stop_queue(store, tmp_path, code):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job(f"x [code:{code}]"), {}, ctx())
    assert err.value.stop_queue and code in str(err.value)


def test_refused_prompt_fails_only_that_job_but_counts(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [code:GENERATION_REFUSED]"), {}, ctx())
    assert not err.value.stop_queue and not err.value.retryable
    assert provider.pacer.used_today() == 1


@pytest.mark.parametrize("prompt", ["x [code:GENERATION_TIMEOUT]", "x [code:DOWNLOAD_FAILED]",
                                    "x [code:JOB_IN_PROGRESS]", "x [running]", "x [empty]"])
def test_transient_failures_are_retryable(store, tmp_path, prompt):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job(prompt), {}, ctx())
    assert err.value.retryable and not err.value.stop_queue


def test_mcp_server_down_stops_queue(store, tmp_path):
    provider, _, _ = make_provider(store, tmp_path)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x [mcp-down]"), {}, ctx())
    assert err.value.stop_queue and "MCP" in str(err.value)


def test_daily_cap_stops_before_calling_mcp(store, tmp_path):
    store.set("web.caps.flow", 1)
    provider, backend, _ = make_provider(store, tmp_path)
    provider.generate(Job("one"), {}, ctx())
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("two"), {}, ctx())
    assert err.value.stop_queue and "cap" in str(err.value).lower()
    assert len(backend.calls) == 1


def test_usage_resets_on_a_new_day(store):
    day = [date(2026, 10, 22)]
    pacer = Pacer("flow", store, today=lambda: day[0])
    pacer.record_use()
    pacer.record_use()
    assert pacer.used_today() == 2
    day[0] = date(2026, 10, 23)
    assert pacer.used_today() == 0
    assert pacer.record_use() == 1


def test_gap_waits_between_jobs_and_honours_stop(store):
    store.set("web.gap_min", 5.0)
    store.set("web.gap_max", 5.0)
    now = [100.0]
    pacer = Pacer("flow", store, clock=lambda: now[0])
    assert pacer.wait_turn(lambda: False)  # first job: no wait
    pacer.mark_done()
    assert not pacer.wait_turn(lambda: True)  # stop while waiting
    now[0] = 106.0
    assert pacer.wait_turn(lambda: False)  # gap already over


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
    from src.gen.fake_provider import FakeProvider
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


def test_web_sessions_tab(qapp, store):
    from src.ui.pages.web_sessions_tab import WebSessionsTab

    class StatusSession(FakeSession):
        def run(self, site, fn, timeout=None):
            return "login"

        def open_site(self, site):
            self.opened = site

    store.set("web.caps.flow", 5)
    Pacer("flow", store).record_use()
    tab = WebSessionsTab(store=store, session=StatusSession())
    row = tab.rows["flow"]
    assert row.usage.text() == "1 / 5" and row.cap.value() == 5
    row.cap.setValue(9)
    assert store.get("web.caps.flow") == 9
    assert tab.do_action("flow", "check") == "login"
    assert tab.do_action("flow", "launch") == "login" and tab.session.opened == "flow"
    tab._on_done("flow", "check", "ok")
    assert "Signed in" in row.status.text()
    tab._on_done("flow", "launch", RuntimeError("Chrome not found"))
    assert "Chrome not found" in row.status.text()
