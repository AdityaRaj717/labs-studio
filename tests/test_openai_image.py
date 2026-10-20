"""OpenAIImageProvider with a mocked HTTP layer (httpx.MockTransport): no network."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from src.gen.models import Job
from src.gen.openai_image import MAX_REFS, OpenAIImageProvider
from src.gen.provider import ProviderError, RunContext, StopRequested

KEY = "sk-test-123"
BASE = "https://api.openai.com/v1"


def png_bytes(color=(10, 200, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return buf.getvalue()


def images_response(n=1, fmt="png") -> dict:
    b64 = base64.b64encode(png_bytes()).decode()
    return {"created": 1, "output_format": fmt, "data": [{"b64_json": b64} for _ in range(n)]}


def make(handler, key=KEY):
    calls: list[httpx.Request] = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    return OpenAIImageProvider(key_source=lambda: key, transport=httpx.MockTransport(wrapped)), calls


def ctx(stop=lambda: False):
    return RunContext(progress=lambda p: None, should_stop=stop)


def opts(**kw):
    return {"model": "gpt-image-2.5-flare", "size": "1024x1024", "quality": "auto",
            "output_format": "png", "background": "auto", "moderation": "auto",
            "count": 1, "timeout": 30} | kw


def test_text_to_image_request():
    provider, calls = make(lambda r: httpx.Response(200, json=images_response()))
    out = provider.generate(Job("a red fox"), opts(quality="high"), ctx())
    assert len(out) == 1 and out[0].ext == "png" and out[0].data == png_bytes()
    req = calls[0]
    assert str(req.url) == f"{BASE}/images/generations"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(req.url)
    body = json.loads(req.content)
    assert body == {"model": "gpt-image-2.5-flare", "prompt": "a red fox", "n": 1,
                    "size": "1024x1024", "quality": "high", "output_format": "png"}


def test_count_uses_n_and_splits_over_ten():
    def handler(r):
        n = json.loads(r.content)["n"]
        return httpx.Response(200, json=images_response(n))

    provider, calls = make(handler)
    out = provider.generate(Job("x"), opts(count=13), ctx())
    assert len(out) == 13
    assert [json.loads(c.content)["n"] for c in calls] == [10, 3]


def test_refs_go_to_edits_as_multipart(tmp_path):
    refs = []
    for i in range(MAX_REFS + 2):
        p = tmp_path / f"ref{i:02}.png"
        p.write_bytes(png_bytes((i, 0, 0)))
        refs.append(p)
    provider, calls = make(lambda r: httpx.Response(200, json=images_response(fmt="webp")))
    out = provider.generate(Job("swap the hat", refs=refs), opts(output_format="webp",
                                                                  background="opaque"), ctx())
    assert out[0].ext == "webp"
    req = calls[0]
    assert str(req.url) == f"{BASE}/images/edits"
    assert req.headers["content-type"].startswith("multipart/form-data")
    content = req.content
    assert content.count(b'name="image[]"') == MAX_REFS
    assert b'name="prompt"\r\n\r\nswap the hat' in content
    assert b'name="background"\r\n\r\nopaque' in content
    assert b"ref00.png" in content


def test_option_fixups():
    provider, _ = make(lambda r: httpx.Response(200))
    p = provider.build_params("x", opts(model="gpt-image-1.5", quality="max",
                                        background="transparent", output_format="jpeg",
                                        moderation="low"), 1)
    assert p["quality"] == "high" and p["output_format"] == "png"
    assert p["background"] == "transparent" and p["moderation"] == "low"
    p = provider.build_params("x", opts(model="gpt-image-2.5-sunburst", quality="xhigh",
                                        size="3840x2160"), 1)
    assert p["quality"] == "xhigh" and p["size"] == "3840x2160"


def test_custom_size_rejected_on_old_model_before_request():
    provider, calls = make(lambda r: httpx.Response(200, json=images_response()))
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(model="gpt-image-1.5", size="2048x2048"), ctx())
    assert not e.value.retryable and not calls


def test_url_delivery_downloaded_without_key():
    def handler(r):
        if r.url.host == "files.example.com":
            return httpx.Response(200, content=png_bytes())
        return httpx.Response(200, json={"data": [{"url": "https://files.example.com/a.png"}]})

    provider, calls = make(handler)
    out = provider.generate(Job("x"), opts(), ctx())
    assert out[0].data == png_bytes()
    assert "authorization" not in calls[1].headers


def test_no_key_fails_before_request():
    provider, calls = make(lambda r: httpx.Response(200), key="  ")
    with pytest.raises(ProviderError, match="No OpenAI API key"):
        provider.generate(Job("x"), opts(), ctx())
    assert not calls


def test_stop_before_call():
    provider, calls = make(lambda r: httpx.Response(200, json=images_response()))
    with pytest.raises(StopRequested):
        provider.generate(Job("x"), opts(), ctx(stop=lambda: True))
    assert not calls


def test_empty_data_is_an_error():
    provider, _ = make(lambda r: httpx.Response(200, json={"data": []}))
    with pytest.raises(ProviderError, match="no image"):
        provider.generate(Job("x"), opts(), ctx())


@pytest.mark.parametrize("code,body,retryable,fragment", [
    (401, {"error": {"message": "Incorrect API key", "code": "invalid_api_key"}}, False, "rejected the API key"),
    (429, {"error": {"message": "slow down", "code": "rate_limit_exceeded"}}, True, "Rate limit"),
    (429, {"error": {"message": "You exceeded your quota", "code": "insufficient_quota"}}, False, "quota"),
    (500, {"error": {"message": "boom"}}, True, "server error 500"),
    (400, {"error": {"message": "Your request was rejected by the safety system",
                     "type": "image_generation_user_error", "code": "moderation_blocked"}},
     False, "content policy"),
    (403, {"error": {"message": "Your organization must be verified"}}, False, "refused the request"),
    (400, {"error": {"message": "Invalid size"}}, False, "error 400"),
])
def test_http_error_mapping(code, body, retryable, fragment):
    provider, _ = make(lambda r: httpx.Response(code, json=body))
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(), ctx())
    assert e.value.retryable is retryable and fragment in str(e.value)
    assert KEY not in str(e.value)


def test_network_error_is_retryable():
    def handler(r):
        raise httpx.ConnectError("down")

    provider, _ = make(handler)
    with pytest.raises(ProviderError) as e:
        provider.generate(Job("x"), opts(), ctx())
    assert e.value.retryable
