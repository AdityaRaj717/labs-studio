"""web_flow_image provider, pacing and queue behaviour with a fake adapter (no browser)."""

from __future__ import annotations

import threading
from datetime import date

import pytest

from src.config import Settings
from src.gen.models import Job, JobStatus
from src.gen.output import save_outputs
from src.gen.provider import ProviderError, RunContext
from src.gen.queue import JobQueue, QueueSettings
from src.gen.web_flow_image import WebFlowImageProvider
from src.web.adapters.base import GenerationRefused, SiteBlocked, UiChanged
from src.web.pacing import Pacer

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.fronted = 0
        self.runs = 0

    def site_lock(self, site):
        return self.lock

    def run(self, site, fn, timeout=None):
        self.runs += 1
        return fn(object())

    def bring_to_front(self, site):
        self.fronted += 1


class FakeAdapter:
    """Scripted adapter: ``script`` maps a prompt word to a behaviour."""

    submitted: list[tuple[str, dict]] = []

    def __init__(self, page, block=None, logged_in=True):
        self.block = block
        self.logged_in = logged_in
        self.prompt = ""
        self.count = 1

    def prepare(self):
        pass

    def detect_block(self):
        return self.block

    def is_logged_in(self):
        return self.logged_in

    def submit(self, prompt, refs, opts):
        self.prompt = prompt
        self.count = opts["count"]
        FakeAdapter.submitted.append((prompt, dict(opts)))
        if "[refused]" in prompt:
            raise GenerationRefused("policy")

    def wait_done(self, timeout, should_stop, progress=lambda p: None):
        progress(1.0)
        if "[quota]" in self.prompt:
            raise SiteBlocked("quota")
        if "[ui]" in self.prompt:
            raise UiChanged("prompt box")

    def collect(self):
        return [] if "[empty]" in self.prompt else [(PNG, "png")] * self.count


@pytest.fixture
def store(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.set("web.gap_min", 0.0)
    s.set("web.gap_max", 0.0)
    s.set("web.caps.flow", 0)
    return s


def make_provider(store, **adapter_kw):
    FakeAdapter.submitted = []
    session = FakeSession()
    provider = WebFlowImageProvider(session=session, pacer=Pacer("flow", store),
                                    adapter_factory=lambda page: FakeAdapter(page, **adapter_kw))
    return provider, session


def ctx():
    return RunContext(progress=lambda p: None, should_stop=lambda: False)


def test_generate_returns_files_and_counts_use(store):
    provider, _ = make_provider(store)
    files = provider.generate(Job("a red fox"), {"count": 2, "timeout": 30}, ctx())
    assert [f.ext for f in files] == ["png", "png"] and files[0].data == PNG
    assert provider.pacer.used_today() == 1
    assert store.get("web.usage.flow")["date"] == date.today().isoformat()


def test_count_is_clamped_to_flow_maximum(store):
    provider, _ = make_provider(store)
    provider.generate(Job("x"), {"count": 8}, ctx())
    assert FakeAdapter.submitted[0][1]["count"] == 4


@pytest.mark.parametrize("kw,needle", [
    ({"logged_in": False}, "sign in"),
    ({"block": "captcha"}, "CAPTCHA"),
    ({"block": "quota"}, "limit"),
])
def test_blocks_stop_queue_and_bring_window_up(store, kw, needle):
    provider, session = make_provider(store, **kw)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x"), {}, ctx())
    assert err.value.stop_queue and not err.value.retryable
    assert needle in str(err.value)
    assert session.fronted == 1
    assert provider.pacer.used_today() == 0  # nothing was submitted


def test_quota_during_wait_and_ui_change_stop_queue(store):
    provider, _ = make_provider(store)
    for prompt in ("[quota] x", "[ui] x"):
        with pytest.raises(ProviderError) as err:
            provider.generate(Job(prompt), {}, ctx())
        assert err.value.stop_queue


def test_refused_prompt_fails_only_that_job(store):
    provider, _ = make_provider(store)
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("[refused] x"), {}, ctx())
    assert not err.value.stop_queue and not err.value.retryable


def test_daily_cap_stops_before_submitting(store):
    store.set("web.caps.flow", 1)
    provider, session = make_provider(store)
    provider.generate(Job("one"), {}, ctx())
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("two"), {}, ctx())
    assert err.value.stop_queue and "cap" in str(err.value).lower()
    assert session.runs == 1


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
    provider, _ = make_provider(store, logged_in=False)
    done = threading.Event()
    q = JobQueue(provider, lambda job, files: save_outputs(job, files, tmp_path), on_finished=done.set)
    jobs = [Job(f"p{i}", index=i) for i in range(1, 5)]
    q.start(jobs, {}, QueueSettings(threads=1, max_retries=3))
    assert q.wait(10) and done.wait(2)
    assert jobs[0].status is JobStatus.FAILED and jobs[0].attempts == 1
    assert all(j.status is JobStatus.STOPPED for j in jobs[1:])


def test_queue_saves_flow_images(store, tmp_path):
    provider, _ = make_provider(store)
    q = JobQueue(provider, lambda job, files: save_outputs(job, files, tmp_path))
    jobs = [Job("a", index=1), Job("b", index=2)]
    q.start(jobs, {"count": 1}, QueueSettings(threads=2))
    assert q.wait(10)
    assert all(j.status is JobStatus.DONE and j.outputs[0].read_bytes() == PNG for j in jobs)


def test_image_page_provider_picker(qapp, store, tmp_path):
    from src.gen.fake_provider import FakeProvider
    from src.ui.generator.page import GeneratorPage

    flow, _ = make_provider(store)
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
