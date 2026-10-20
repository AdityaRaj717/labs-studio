"""GeminiImageProvider with a mocked HTTP layer (httpx.MockTransport): no network."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from src.gen.gemini_image import (
    MAX_REFS, REF_MAX_SIDE, GeminiImageProvider, encode_ref, parse_response,
)
from src.gen.models import Job
from src.gen.provider import ProviderError, RunContext, StopRequested

KEY = "test-key-123"


def png_bytes(size=(4, 4), color=(200, 10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def image_response(n_images=1, mime="image/png", extra_parts=()) -> dict:
    parts = list(extra_parts) + [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(png_bytes()).decode()}}
        for _ in range(n_images)
    ]
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]}


def make(handler, key=KEY):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return GeminiImageProvider(key_source=lambda: key, transport=httpx.MockTransport(wrapped)), calls


def ctx(progress=None, stop=lambda: False):
    return RunContext(progress=progress or (lambda p: None), should_stop=stop)


def opts(**kw):
    return {"model": "gemini-3.1-flash-image", "aspect": "16:9", "image_size": "2K",
            "count": 1, "timeout": 30} | kw


# ---- request building ---------------------------------------------------
def test_request_url_headers_and_body():
    provider, calls = make(lambda r: httpx.Response(200, json=image_response()))
    out = provider.generate(Job("a red fox"), opts(), ctx())
    assert len(out) == 1 and out[0].ext == "png" and out[0].data == png_bytes()

    req = calls[0]
    assert req.method == "POST"
    assert str(req.url) == ("https://generativelanguage.googleapis.com/v1beta/models/"
                            "gemini-3.1-flash-image:generateContent")
    assert req.headers["x-goog-api-key"] == KEY
    assert KEY not in str(req.url)
    body = json.loads(req.content)
    assert body["contents"][0]["parts"] == [{"text": "a red fox"}]
    assert body["generationConfig"] == {
        "responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"}}


def test_image_size_omitted_for_models_without_it():
    provider, _ = make(lambda r: httpx.Response(200))
    _, body = provider.build_request("x", [], opts(model="gemini-2.5-flash-image"))
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9"}


def test_refs_sent_as_inline_data_before_prompt(tmp_path):
    ref = tmp_path / "fox.png"
    ref.write_bytes(png_bytes())
    jpg = tmp_path / "owl.jpg"
    Image.new("RGB", (3, 3)).save(jpg, "JPEG")
    provider, _ = make(lambda r: httpx.Response(200))
    _, body = provider.build_request("p", [ref, jpg], opts())
    parts = body["contents"][0]["parts"]
    assert parts[0]["inlineData"] == {"mimeType": "image/png",
                                      "data": base64.b64encode(png_bytes()).decode()}
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert parts[2] == {"text": "p"}

    _, body = provider.build_request("p", [ref] * (MAX_REFS + 3), opts())
    assert len(body["contents"][0]["parts"]) == MAX_REFS + 1


def test_big_ref_is_shrunk_to_jpeg(tmp_path):
    big = tmp_path / "big.png"
    Image.new("RGB", (REF_MAX_SIDE + 500, 100)).save(big, "PNG")
    mime, data = encode_ref(big)
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(base64.b64decode(data))) as img:
        assert max(img.size) == REF_MAX_SIDE


def test_count_makes_sequential_calls_and_reports_progress():
    provider, calls = make(lambda r: httpx.Response(200, json=image_response()))
    seen: list[float] = []
    out = provider.generate(Job("p"), opts(count=3), ctx(progress=seen.append))
    assert len(out) == 3 and len(calls) == 3
    assert seen[-1] == 1.0 and seen == sorted(seen)


def test_stop_before_next_call():
    provider, calls = make(lambda r: httpx.Response(200, json=image_response()))
    stops = iter([False, True])
    with pytest.raises(StopRequested):
        provider.generate(Job("p"), opts(count=3), ctx(stop=lambda: next(stops)))
    assert len(calls) == 1


# ---- response parsing ---------------------------------------------------
def test_parse_skips_text_and_thought_parts_and_maps_ext():
    payload = image_response(2, mime="image/jpeg", extra_parts=[
        {"text": "Here you go"},
        {"thought": True, "inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"x").decode()}},
    ])
    assert [f.ext for f in parse_response(payload)] == ["jpg", "jpg"]


def test_parse_snake_case_inline_data():
    payload = {"candidates": [{"content": {"parts": [
        {"inline_data": {"mime_type": "image/webp", "data": base64.b64encode(b"abc").decode()}}]}}]}
    assert parse_response(payload)[0].ext == "webp"


# ---- error mapping --------------------------------------------------------
def google_error(code, status, message, reason=""):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}] if reason else []
    return {"error": {"code": code, "message": message, "status": status, "details": details}}


@pytest.mark.parametrize("code,body,retryable,fragment", [
    (400, google_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                       "API_KEY_INVALID"), False, "rejected the API key"),
    (403, google_error(403, "PERMISSION_DENIED", "Permission denied"), False, "rejected the API key"),
    (429, google_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded"), True, "Rate limit"),
    (500, google_error(500, "INTERNAL", "Internal error"), True, "server error 500"),
    (503, google_error(503, "UNAVAILABLE", "The model is overloaded"), True, "server error 503"),
    (404, google_error(404, "NOT_FOUND", "models/nope is not found"), False, "Gemini error 404"),
])
def test_http_error_mapping(code, body, retryable, fragment):
    provider, _ = make(lambda r: httpx.Response(code, json=body))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable is retryable
    assert fragment in str(info.value)
    assert KEY not in str(info.value)


def test_non_json_error_body():
    provider, _ = make(lambda r: httpx.Response(502, text="<html>Bad Gateway</html>"))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable


def test_network_errors_are_retryable():
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    provider, _ = make(refused)
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable and "Network error" in str(info.value)

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, _ = make(slow)
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert info.value.retryable and "timeout" in str(info.value)


def test_prompt_block_is_content_policy():
    payload = {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}
    provider, _ = make(lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert not info.value.retryable and "PROHIBITED_CONTENT" in str(info.value)


@pytest.mark.parametrize("reason", ["IMAGE_SAFETY", "SAFETY", "IMAGE_PROHIBITED_CONTENT"])
def test_finish_reason_refusal(reason):
    payload = {"candidates": [{"content": {"parts": [{"text": "Not able to make that."}]},
                               "finishReason": reason}]}
    with pytest.raises(ProviderError) as info:
        parse_response(payload)
    assert not info.value.retryable
    assert "content policy" in str(info.value) and reason in str(info.value)


def test_no_image_returned():
    payload = {"candidates": [{"content": {"parts": [{"text": "Describe more?"}]},
                               "finishReason": "NO_IMAGE"}]}
    with pytest.raises(ProviderError, match=r"No image returned \(NO_IMAGE\): Describe more\?"):
        parse_response(payload)


# ---- key handling -----------------------------------------------------------
def test_missing_key_fails_before_any_request():
    provider, calls = make(lambda r: httpx.Response(200, json=image_response()), key="  ")
    with pytest.raises(ProviderError) as info:
        provider.generate(Job("p"), opts(), ctx())
    assert not info.value.retryable and "No Gemini API key" in str(info.value)
    assert calls == []


def test_key_read_per_job_so_new_key_applies_without_restart():
    keys = iter(["", KEY])
    seen = []

    def handler(r):
        seen.append(r.headers["x-goog-api-key"])
        return httpx.Response(200, json=image_response())

    provider = GeminiImageProvider(key_source=lambda: next(keys), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        provider.generate(Job("p"), opts(), ctx())
    provider.generate(Job("p"), opts(), ctx())
    assert seen == [KEY]
