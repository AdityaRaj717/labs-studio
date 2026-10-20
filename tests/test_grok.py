"""GrokProvider (xAI) with a mocked HTTP layer and a fake clock: no network, no sleeping."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from src.gen.grok import MAX_EDIT_REFS, GrokProvider, parse_video
from src.gen.models import Job
from src.gen.provider import ProviderError, RunContext, StopRequested

KEY = "xai-test-123"
BASE = "https://api.x.ai/v1"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"
VIDEO_URL = "https://vidgen.x.ai/out/abc.mp4"


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def sleep(self, d):
        self.t += d

    def clock(self):
        return self.t


def jpg_bytes(color=(10, 10, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "JPEG")
    return buf.getvalue()


def png(path, color=(200, 10, 10)):
    Image.new("RGB", (4, 4), color).save(path, "PNG")
    return path


def images_response(n=1, mime="image/jpeg") -> dict:
    b64 = base64.b64encode(jpg_bytes()).decode()
    return {"data": [{"b64_json": b64, "mime_type": mime} for _ in range(n)],
            "usage": {"cost_in_usd_ticks": 1}}


def make(handler, key=KEY):
    calls: list[httpx.Request] = []
    ft = FakeTime()

    def wrapped(request):
        calls.append(request)
        return handler(request)

    provider = GrokProvider(key_source=lambda: key, transport=httpx.MockTransport(wrapped),
                            sleep=ft.sleep, clock=ft.clock)
    return provider, calls, ft


def ctx(stop=lambda: False, progress=None):
    return RunContext(progress=progress or (lambda p: None), should_stop=stop)


def opts(**kw):
    return {"mode": "image", "image_model": "grok-imagine-image-2.0",
            "video_model": "grok-imagine-video-1.5", "aspect": "16:9", "image_resolution": "2k",
            "image_quality": "auto", "video_resolution": "720p", "video_duration": 6,
            "video_audio": True, "video_refs": "auto", "poll_interval": 5, "timeout": 600,
            "count": 1} | kw


def body_of(req):
    return json.loads(req.content)


def video_handler(polls, final=None, submit_code=200):
    """Submit → request_id; ``polls`` pending replies, then ``final``; video URL → MP4."""
    state = {"polls": 0}
    final = final or {"status": "done", "video": {"url": VIDEO_URL, "duration": 6,
                                                  "respect_moderation": True}, "progress": 100}

    def handler(r):
        if r.url.host == "vidgen.x.ai":
            return httpx.Response(200, content=MP4)
        if r.method == "POST":
            return httpx.Response(submit_code, json={"request_id": "req-1"})
        state["polls"] += 1
        if state["polls"] <= polls:
            return httpx.Response(202, json={"status": "pending", "progress": 40})
        return httpx.Response(200, json=final)

    return handler


# ---- images -------------------------------------------------------------
def test_text_to_image_request():
    provider, calls, _ = make(lambda r: httpx.Response(200, json=images_response()))
    out = provider.generate(Job("a red fox"), opts(image_quality="low"), ctx())
    assert len(out) == 1 and out[0].ext == "jpg" and out[0].data == jpg_bytes()
    req = calls[0]
    assert str(req.url) == f"{BASE}/images/generations"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body_of(req) == {"model": "grok-imagine-image-2.0", "prompt": "a red fox", "n": 1,
                            "response_format": "b64_json", "resolution": "2k",
                            "aspect_ratio": "16:9", "quality": "low"}


def test_auto_aspect_and_quality_omitted_for_other_models():
    provider, *_ = make(lambda r: httpx.Response(200))
    _, body = provider.build_image_request("x", [], opts(aspect="auto", image_quality="low",
                                                         image_model="grok-imagine-image"))
    assert "aspect_ratio" not in body and "quality" not in body


def test_count_uses_n():
    def handler(r):
        return httpx.Response(200, json=images_response(body_of(r)["n"]))

    provider, calls, _ = make(handler)
    assert len(provider.generate(Job("x"), opts(count=12), ctx())) == 12
    assert [body_of(c)["n"] for c in calls] == [10, 2]


def test_single_ref_is_image_edit(tmp_path):
    provider, calls, _ = make(lambda r: httpx.Response(200, json=images_response(mime="image/png")))
    out = provider.generate(Job("make it night", refs=[png(tmp_path / "a.png")]), opts(), ctx())
    assert out[0].ext == "png"
    assert str(calls[0].url) == f"{BASE}/images/edits"
    body = body_of(calls[0])
    assert body["image"]["url"].startswith("data:image/png;base64,") and "images" not in body


def test_many_refs_are_images_capped(tmp_path):
    refs = [png(tmp_path / f"r{i}.png", (i, 0, 0)) for i in range(MAX_EDIT_REFS + 2)]
    provider, calls, _ = make(lambda r: httpx.Response(200, json=images_response()))
    provider.generate(Job("combine <IMAGE_0> and <IMAGE_1>", refs=refs), opts(), ctx())
    body = body_of(calls[0])
    assert len(body["images"]) == MAX_EDIT_REFS and "image" not in body


def test_image_url_delivery_downloaded_without_key():
    def handler(r):
        if r.url.host == "imgen.x.ai":
            return httpx.Response(200, content=jpg_bytes())
        return httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/a.jpg"}]})

    provider, calls, _ = make(handler)
    assert provider.generate(Job("x"), opts(), ctx())[0].data == jpg_bytes()
    assert "authorization" not in calls[1].headers


def test_no_key_fails_before_request():
    provider, calls, _ = make(lambda r: httpx.Response(200), key="")
    with pytest.raises(ProviderError, match="No xAI API key"):
        provider.generate(Job("x"), opts(), ctx())
    assert not calls


@pytest.mark.parametrize("code,body,retryable,fragment", [
    (401, {"code": "unauthenticated", "error": "Incorrect API key provided"}, False, "rejected the API key"),
    (429, {"error": "Too many requests"}, True, "Rate limit"),
    (503, {"error": "overloaded"}, True, "server error 503"),
    (400, {"code": "invalid_argument", "error": "Generated image rejected by content moderation."},
     False, "content policy"),
    (400, {"error": {"message": "bad aspect", "code": "invalid_argument"}}, False, "error 400"),
])
def test_http_error_mapping(code, body, retryable, fragment):
    provider, *_ = make(lambda r: httpx.Response(code, json=body))
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(), ctx())
    assert e.value.retryable is retryable and fragment in str(e.value)
    assert KEY not in str(e.value)


# ---- video --------------------------------------------------------------
def test_text_to_video_submit_poll_download():
    seen = []
    provider, calls, ft = make(video_handler(polls=2))
    out = provider.generate(Job("a whale jumps"), opts(mode="video", video_audio=False),
                            ctx(progress=seen.append))
    assert len(out) == 1 and out[0].ext == "mp4" and out[0].data == MP4
    submit = calls[0]
    assert str(submit.url) == f"{BASE}/videos/generations"
    assert body_of(submit) == {"model": "grok-imagine-video-1.5", "duration": 6,
                               "resolution": "720p", "prompt": "a whale jumps",
                               "aspect_ratio": "16:9", "generate_audio": False}
    assert [str(c.url) for c in calls[1:4]] == [f"{BASE}/videos/req-1"] * 3
    assert all(c.headers["authorization"] == f"Bearer {KEY}" for c in calls[:4])
    assert "authorization" not in calls[4].headers  # the download
    assert ft.t == pytest.approx(15)
    assert seen[-1] == 1.0 and seen == sorted(seen)


def test_video_one_ref_is_start_frame(tmp_path):
    provider, *_ = make(lambda r: httpx.Response(200))
    _, body = provider.build_video_request("pan right", [png(tmp_path / "a.png")],
                                           opts(mode="video", aspect="auto"))
    assert body["image"]["url"].startswith("data:image/png;base64,")
    assert "reference_images" not in body and "aspect_ratio" not in body


def test_video_many_refs_are_references_or_forced_start(tmp_path):
    refs = [png(tmp_path / f"r{i}.png", (i, 0, 0)) for i in range(3)]
    provider, *_ = make(lambda r: httpx.Response(200))
    _, body = provider.build_video_request("x", refs, opts(mode="video"))
    assert len(body["reference_images"]) == 3 and "image" not in body
    _, body = provider.build_video_request("x", refs, opts(mode="video", video_refs="start_frame"))
    assert "image" in body and "reference_images" not in body
    _, body = provider.build_video_request("x", refs[:1], opts(mode="video", video_refs="references"))
    assert len(body["reference_images"]) == 1


def test_video_count_submits_separate_jobs():
    provider, calls, _ = make(video_handler(polls=0))
    out = provider.generate(Job("x"), opts(mode="video", count=2), ctx())
    assert len(out) == 2
    assert sum(1 for c in calls if c.method == "POST") == 2


def test_stop_during_polling():
    polls = {"n": 0}

    def stop():
        return polls["n"] >= 1

    base = video_handler(polls=50)

    def handler(r):
        if r.method == "GET":
            polls["n"] += 1
        return base(r)

    provider, calls, _ = make(handler)
    with pytest.raises(StopRequested):
        provider.generate(Job("x"), opts(mode="video"), ctx(stop=stop))
    assert polls["n"] == 1


def test_timeout_not_retryable():
    provider, *_ = make(video_handler(polls=10_000))
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(mode="video", timeout=60), ctx())
    assert "timed out" in str(e.value) and not e.value.retryable


def test_poll_flakiness_tolerated_then_gives_up():
    state = {"n": 0}
    good = video_handler(polls=0)

    def flaky_once(r):
        if r.method == "GET" and r.url.host == "api.x.ai":
            state["n"] += 1
            if state["n"] <= 2:
                return httpx.Response(503)
        return good(r)

    provider, *_ = make(flaky_once)
    assert provider.generate(Job("x"), opts(mode="video"), ctx())[0].data == MP4

    def always_down(r):
        if r.method == "GET":
            return httpx.Response(503)
        return good(r)

    provider, *_ = make(always_down)
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(mode="video"), ctx())
    assert "Lost contact" in str(e.value) and not e.value.retryable


def test_submit_errors_mapped():
    provider, *_ = make(lambda r: httpx.Response(429, json={"error": "slow down"}))
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(mode="video"), ctx())
    assert e.value.retryable


@pytest.mark.parametrize("data,fragment,retryable", [
    ({"status": "failed", "error": {"code": "invalid_argument", "message": "bad image"}},
     "failed (bad image)", False),
    ({"status": "failed", "error": {"code": "internal_error", "message": "oops"}}, "failed", True),
    ({"status": "failed", "error": {"code": "permission_denied",
                                    "message": "Prompt blocked by content moderation"}},
     "content policy", False),
    ({"status": "done", "video": {"url": None, "respect_moderation": False}}, "moderation", False),
    ({"status": "expired"}, "expired", False),
])
def test_parse_video_failures(data, fragment, retryable):
    with pytest.raises(ProviderError) as e:
        parse_video(data)
    assert fragment in str(e.value) and e.value.retryable is retryable


def test_failed_poll_through_generate():
    final = {"status": "failed", "error": {"code": "invalid_argument", "message": "nope"}}
    provider, *_ = make(video_handler(polls=1, final=final))
    with pytest.raises(ProviderError, match="nope"):
        provider.generate(Job("x"), opts(mode="video"), ctx())
