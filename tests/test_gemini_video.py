"""GeminiVideoProvider (Omni Flash, Interactions API) with a mocked HTTP layer: no network."""

from __future__ import annotations

import base64
import io
import json
import time

import httpx
import pytest
from PIL import Image

from src.config import Settings
from src.gen.gemini_video import GeminiVideoProvider, parse_interaction
from src.gen.models import Job, JobStatus
from src.gen.provider import ProviderError, RunContext, StopRequested

KEY = "test-key-123"
BASE = "https://generativelanguage.googleapis.com/v1beta"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"


class FakeTime:
    """sleep() advances clock(); nothing really waits."""

    def __init__(self):
        self.t = 0.0
        self.slept = 0.0

    def sleep(self, d):
        self.t += d
        self.slept += d

    def clock(self):
        return self.t


def png(path, color=(200, 10, 10)):
    Image.new("RGB", (4, 4), color).save(path, "PNG")
    return path


def done(video=None, status="completed", text=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if video is not False:
        content.append(video or {"type": "video", "mime_type": "video/mp4",
                                 "data": base64.b64encode(MP4).decode()})
    return {"id": "v1_abc", "status": status, "object": "interaction",
            "steps": [{"type": "user_input", "content": [{"type": "text", "text": "p"}]},
                      {"type": "thought", "content": [{"type": "thought", "text": "..."}]},
                      {"type": "model_output", "content": content}]}


PENDING = {"id": "v1_abc", "status": "in_progress"}


def make(handler, key=KEY):
    calls: list[httpx.Request] = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    ft = FakeTime()
    provider = GeminiVideoProvider(key_source=lambda: key, transport=httpx.MockTransport(wrapped),
                                   sleep=ft.sleep, clock=ft.clock)
    provider.fake_time = ft
    return provider, calls


def scripted(*responses):
    """Handler answering submit, then each poll, from a list (last one repeats)."""
    queue = list(responses)

    def handler(request):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return item(request) if callable(item) else item

    return handler


def ok(payload):
    return httpx.Response(200, json=payload)


def opts(**kw):
    return {"model": "gemini-omni-1.1-flash", "aspect": "16:9", "resolution": "720p",
            "duration": "auto", "task": "auto", "poll_interval": 10, "timeout": 600, "count": 1} | kw


def ctx(stop=lambda: False):
    seen = []
    c = RunContext(progress=seen.append, should_stop=stop)
    c.seen = seen
    return c


def body_of(request):
    return json.loads(request.content)


# ---- request building -------------------------------------------------------
def test_text_to_video_request():
    provider, calls = make(lambda r: ok(done()))
    out = provider.generate(Job("a fox runs"), opts(aspect="9:16", resolution="1080p"), ctx())
    req = calls[0]
    assert req.method == "POST" and str(req.url) == f"{BASE}/interactions"
    assert req.headers["x-goog-api-key"] == KEY and KEY not in str(req.url)
    body = body_of(req)
    assert body["model"] == "gemini-omni-1.1-flash"
    assert body["input"] == "a fox runs"
    assert body["response_format"] == {"type": "video", "aspect_ratio": "9:16", "resolution": "1080p"}
    assert body["background"] is True and body["store"] is True
    assert "generation_config" not in body
    assert [(o.data, o.ext) for o in out] == [(MP4, "mp4")]


def test_image_to_video_start_frame(tmp_path):
    provider, calls = make(lambda r: ok(done()))
    job = Job("the fox wakes up", refs=[png(tmp_path / "fox.png")])
    provider.generate(job, opts(), ctx())
    items = body_of(calls[0])["input"]
    assert [i["type"] for i in items] == ["image", "text"]
    assert items[0]["mime_type"] == "image/png" and base64.b64decode(items[0]["data"])[:4] == b"\x89PNG"
    assert items[1]["text"] == "the fox wakes up"


def test_start_and_end_frame_in_order_extra_dropped(tmp_path):
    refs = [png(tmp_path / f"{n}.png", (n * 40, 0, 0)) for n in (1, 2, 3)]
    provider, calls = make(lambda r: ok(done()))
    provider.generate(Job("morph", refs=refs), opts(task="image_to_video"), ctx())
    body = body_of(calls[0])
    images = [i for i in body["input"] if i["type"] == "image"]
    assert len(images) == 2
    first = Image.open(io.BytesIO(base64.b64decode(images[0]["data"]))).getpixel((0, 0))
    assert first[0] == 40  # 1.png is the start frame
    assert body["generation_config"] == {"video_config": {"task": "image_to_video"}}


def test_reference_mode_sends_up_to_three(tmp_path):
    refs = [png(tmp_path / f"{n}.png") for n in range(5)]
    provider, calls = make(lambda r: ok(done()))
    provider.generate(Job("hero", refs=refs), opts(task="reference_to_video"), ctx())
    body = body_of(calls[0])
    assert sum(i["type"] == "image" for i in body["input"]) == 3


def test_text_mode_ignores_refs_and_duration_hint(tmp_path):
    provider, calls = make(lambda r: ok(done()))
    provider.generate(Job("a whale.", refs=[png(tmp_path / "w.png")]),
                      opts(task="text_to_video", duration="6"), ctx())
    body = body_of(calls[0])
    assert body["input"] == "a whale. Make the clip about 6 seconds long."
    assert body["generation_config"]["video_config"]["task"] == "text_to_video"


# ---- polling ----------------------------------------------------------------
def test_poll_loop_until_done():
    provider, calls = make(scripted(ok({"id": "v1_abc", "status": "queued"}), ok(PENDING),
                                    ok(PENDING), ok(done())))
    c = ctx()
    out = provider.generate(Job("p"), opts(poll_interval=10), c)
    assert [r.method for r in calls] == ["POST", "GET", "GET", "GET"]
    assert all(str(r.url) == f"{BASE}/interactions/v1_abc" for r in calls[1:])
    assert all(r.headers["x-goog-api-key"] == KEY for r in calls)
    assert provider.fake_time.slept == pytest.approx(30)
    assert out[0].data == MP4
    assert c.seen == sorted(c.seen) and c.seen[-1] == 1.0 and 0.05 < c.seen[-3] < 0.95


def test_uri_delivery_is_downloaded_with_key_header():
    video = {"type": "video", "mime_type": "video/mp4", "uri": f"{BASE}/files/abc:download?alt=media"}

    def handler(r):
        if "files/abc" in str(r.url):
            return httpx.Response(302, headers={"location": "https://cdn.example/v.mp4"})
        if r.url.host == "cdn.example":
            return httpx.Response(200, content=MP4)
        return ok(done(video))

    provider, calls = make(handler)
    out = provider.generate(Job("p"), opts(), ctx())
    assert out[0].data == MP4 and out[0].ext == "mp4"
    dl = [r for r in calls if "files/abc" in str(r.url)][0]
    assert dl.headers["x-goog-api-key"] == KEY and "key=" not in str(dl.url)
    cdn = [r for r in calls if r.url.host == "cdn.example"][0]
    assert "x-goog-api-key" not in cdn.headers  # key never leaves the API host


def test_background_rejected_falls_back_to_sync():
    def handler(r):
        if body_of(r)["background"]:
            return httpx.Response(400, json={"error": {"code": 400, "message": "background is not supported for this model",
                                                       "status": "INVALID_ARGUMENT"}})
        return ok(done())

    provider, calls = make(handler)
    assert provider.generate(Job("p"), opts(), ctx())[0].data == MP4
    assert body_of(calls[1])["background"] is False and body_of(calls[1])["store"] is False


def test_stop_during_polling_cancels():
    polls = []

    def handler(r):
        if r.url.path.endswith("/cancel"):
            return ok({"id": "v1_abc", "status": "cancelled"})
        if r.method == "GET":
            polls.append(r)
        return ok(PENDING)

    provider, calls = make(handler)
    with pytest.raises(StopRequested):
        provider.generate(Job("p"), opts(), ctx(stop=lambda: len(polls) >= 2))
    assert str(calls[-1].url) == f"{BASE}/interactions/v1_abc/cancel" and calls[-1].method == "POST"


def test_timeout_cancels_and_is_not_retryable():
    provider, calls = make(lambda r: ok(PENDING))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(timeout=60, poll_interval=10), ctx())
    assert not info.value.retryable and "timed out" in str(info.value)
    assert calls[-1].url.path.endswith("/v1_abc/cancel")


def test_poll_flakiness_tolerated_then_gives_up():
    provider, _ = make(scripted(ok(PENDING), httpx.Response(503), httpx.Response(429), ok(done())))
    assert provider.generate(Job("p"), opts(), ctx())[0].data == MP4

    provider, _ = make(scripted(ok(PENDING), httpx.Response(503)))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert not info.value.retryable and "Lost contact" in str(info.value)


# ---- errors -----------------------------------------------------------------
@pytest.mark.parametrize("code,body,retryable,fragment", [
    (400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                     "status": "INVALID_ARGUMENT",
                     "details": [{"reason": "API_KEY_INVALID"}]}}, False, "rejected the API key"),
    (403, {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}},
     False, "rejected the API key"),
    (429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
     True, "Rate limit"),
    (500, {"error": {"code": 500, "message": "Internal", "status": "INTERNAL"}}, True, "server error 500"),
    (503, {"error": {"code": 503, "message": "Overloaded", "status": "UNAVAILABLE"}}, True, "server error 503"),
    (404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}},
     False, "error 404"),
])
def test_submit_http_error_mapping(code, body, retryable, fragment):
    provider, _ = make(lambda r: httpx.Response(code, json=body))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable is retryable and fragment in str(info.value)
    assert KEY not in str(info.value)


def test_submit_network_error_is_retryable():
    def boom(r):
        raise httpx.ConnectError("no route")

    provider, _ = make(boom)
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable and "Network error" in str(info.value)


def test_operation_failed_is_not_retryable():
    failed = {"id": "v1_abc", "status": "failed",
              "errors": [{"code": "internal", "message": "Constraint violated in renderer"}]}
    provider, _ = make(scripted(ok(PENDING), ok(failed)))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert not info.value.retryable
    assert str(info.value) == "Video generation failed: Constraint violated in renderer"


@pytest.mark.parametrize("message", [
    "The prompt was blocked by safety filters.",
    "Output filtered: Responsible AI policy",
    "Video violates our usage policies (PROHIBITED_CONTENT)",
])
def test_content_policy_refusal(message):
    failed = {"id": "v1_abc", "status": "failed", "errors": [{"code": "x", "message": message}]}
    with pytest.raises(ProviderError) as info:
        parse_interaction(failed)
    assert not info.value.retryable and "content policy" in str(info.value)


def test_completed_without_video():
    with pytest.raises(ProviderError, match=r"No video returned \(completed\): Can you describe"):
        parse_interaction(done(video=False, text="Can you describe the scene?"))
    with pytest.raises(ProviderError, match="content policy"):
        parse_interaction(done(video=False, text="I can't make that; it was blocked."))


def test_cancelled_by_server():
    with pytest.raises(ProviderError, match="cancelled"):
        parse_interaction({"id": "x", "status": "cancelled"})


def test_missing_key_fails_before_any_request():
    provider, calls = make(lambda r: ok(done()), key="")
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert not info.value.retryable and "No Gemini API key" in str(info.value)
    assert calls == []


def test_count_makes_sequential_interactions():
    provider, calls = make(lambda r: ok(done()))
    c = ctx()
    assert len(provider.generate(Job("p"), opts(count=2), c)) == 2
    assert len(calls) == 2 and c.seen[-1] == 1.0


# ---- UI -----------------------------------------------------------------------
def test_mp4_output_gets_placeholder_thumb(qapp, tmp_path):
    from PySide6.QtCore import Qt

    from src.ui.generator.prompt_model import COL_OUTPUT, PromptTableModel

    clip = tmp_path / "001_x_1.mp4"
    clip.write_bytes(MP4)
    model = PromptTableModel()
    job = model.add_prompts(["p"])[0]
    job.outputs = [clip]
    pix = model.data(model.index(0, COL_OUTPUT), Qt.ItemDataRole.DecorationRole)
    assert pix is not None and not pix.isNull() and pix.width() > pix.height()


def video_page(tmp_path, key=KEY):
    from src.ui.generator.page import GeneratorPage

    store = Settings(tmp_path / "settings.json")
    for k, v in {"save_dir": str(tmp_path / "out"), "delay_min": 0.0, "delay_max": 0.0,
                 "threads": 1, "max_retries": 0, "subdir_mode": "none"}.items():
        store.set(f"pages.test_video.{k}", v)
    ft = FakeTime()

    def per_request(r):  # submit -> pending, poll -> done, for every job
        return ok(PENDING) if r.method == "POST" else ok(done())

    provider = GeminiVideoProvider(key_source=lambda: key, transport=httpx.MockTransport(per_request),
                                   sleep=ft.sleep, clock=ft.clock)
    return GeneratorPage("test_video", provider, store=store)


def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_page_batch_saves_mp4(qapp, tmp_path):
    page = video_page(tmp_path)
    page.add_prompts(["a red fox", "a blue whale"])
    assert page.start() == 2
    assert run_until(qapp, lambda: not page.queue.is_running()
                     and all(j.status is JobStatus.DONE for j in page.jobs))
    files = sorted((tmp_path / "out").glob("*.mp4"))
    assert [f.name for f in files] == ["001_a-red-fox_1.mp4", "002_a-blue-whale_1.mp4"]
    assert files[0].read_bytes() == MP4
    page.shutdown()


def test_page_without_key_shows_error_row(qapp, tmp_path):
    from src.ui.generator.prompt_model import COL_OUTPUT

    page = video_page(tmp_path, key="")
    page.add_prompts(["a red fox"])
    page.start()
    assert run_until(qapp, lambda: not page.queue.is_running() and page.jobs[0].status is JobStatus.FAILED)
    text = page.model.data(page.model.index(0, COL_OUTPUT))
    assert "No Gemini API key" in text
    page.shutdown()


def test_main_window_registers_flow_video(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.ui.generator.page import GeneratorPage
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("flow_video")
    page = window.page("flow_video")
    assert isinstance(page, GeneratorPage) and isinstance(page.provider, GeminiVideoProvider)
    window.close()
