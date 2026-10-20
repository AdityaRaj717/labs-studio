"""Gemini API native image generation (``models/{model}:generateContent``).

Uses the official REST endpoint with the user's own key. Images come back with
Google's SynthID watermark and are saved unchanged.
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image

from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY_ID = "gemini"

MODELS = [
    "gemini-3.1-flash-image",
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
    "gemini-3.1-flash-lite-image",
    "gemini-2.5-flash-image",
]
ASPECTS = ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
SIZES = ["1K", "2K", "4K"]
# Models that don't take imageConfig.imageSize (2.5 has no size option, Lite is 1K only).
NO_SIZE_MODELS = {"gemini-2.5-flash-image", "gemini-3.1-flash-lite-image"}

MAX_REFS = 14
REF_MAX_BYTES = 4 * 1024 * 1024
REF_MAX_SIDE = 2048

POLICY_REASONS = {
    "SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT",
    "BLOCKLIST", "SPII", "RECITATION",
}
RETRY_STATUS = {429, 500, 502, 503, 504}
EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _no_key_message() -> str:
    return "No Gemini API key. Add one in Settings → API keys."


class GeminiImageProvider(Provider):
    key = "gemini_image"
    name = "Gemini API (image)"

    def __init__(self, key_source: Callable[[], str] | None = None,
                 transport: httpx.BaseTransport | None = None, api_base: str = API_BASE):
        if key_source is None:
            from src.keys import get_key

            key_source = lambda: get_key(KEY_ID)  # noqa: E731
        self.key_source = key_source
        self.api_base = api_base.rstrip("/")
        self._client = httpx.Client(transport=transport)

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField("model", "gen_model", "choice", MODELS[0], MODELS),
            ConfigField("aspect", "gen_aspect", "choice", "1:1", ASPECTS),
            ConfigField("image_size", "gen_image_size", "choice", "1K", SIZES),
            ConfigField("timeout", "gen_timeout", "int", 120, minimum=10, maximum=600),
        ]

    # ---- request ----------------------------------------------------
    def build_request(self, prompt: str, refs: list[Path], options: dict[str, Any]) -> tuple[str, dict]:
        model = options.get("model") or MODELS[0]
        parts: list[dict] = []
        if len(refs) > MAX_REFS:
            log.warning("%d reference images; sending the first %d", len(refs), MAX_REFS)
        for ref in refs[:MAX_REFS]:
            mime, data = encode_ref(Path(ref))
            parts.append({"inlineData": {"mimeType": mime, "data": data}})
        parts.append({"text": prompt})

        image_config: dict[str, str] = {"aspectRatio": options.get("aspect") or "1:1"}
        size = options.get("image_size") or "1K"
        if model not in NO_SIZE_MODELS:
            image_config["imageSize"] = size
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": image_config},
        }
        return f"{self.api_base}/models/{model}:generateContent", body

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        key = (self.key_source() or "").strip()
        if not key:
            raise ProviderError(_no_key_message())
        count = max(1, int(options.get("count", 1)))
        timeout = float(options.get("timeout", 120))
        url, body = self.build_request(job.prompt, job.refs, options)
        outputs: list[OutputFile] = []
        ctx.progress(0.05)
        for n in range(count):
            if ctx.should_stop():
                raise StopRequested()
            outputs.extend(self._call(url, body, key, timeout))
            ctx.progress((n + 1) / count)
        return outputs

    def _call(self, url: str, body: dict, key: str, timeout: float) -> list[OutputFile]:
        try:
            resp = self._client.post(url, json=body, timeout=timeout,
                                     headers={"x-goog-api-key": key})
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Network timeout: {type(exc).__name__}", retryable=True) from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error: {type(exc).__name__}", retryable=True) from None
        if resp.status_code != 200:
            raise map_http_error(resp)
        try:
            payload = resp.json()
        except ValueError:
            raise ProviderError("Gemini returned a response that isn't JSON", retryable=True) from None
        return parse_response(payload)

    def close(self) -> None:
        self._client.close()


# ---- helpers (module level so tests can hit them directly) ------------
def encode_ref(path: Path) -> tuple[str, str]:
    """Return (mime, base64) for a reference image, shrinking big ones to JPEG."""
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    needs_shrink = len(raw) > REF_MAX_BYTES or mime not in ("image/png", "image/jpeg", "image/webp")
    if not needs_shrink:
        with Image.open(io.BytesIO(raw)) as img:
            needs_shrink = max(img.size) > REF_MAX_SIDE
    if needs_shrink:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            img.thumbnail((REF_MAX_SIDE, REF_MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=90)
        raw, mime = buf.getvalue(), "image/jpeg"
    return mime, base64.b64encode(raw).decode("ascii")


def _error_info(resp: httpx.Response) -> tuple[str, str, str]:
    """(message, status, reason) from a Google API error body, best effort."""
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return resp.text[:200].strip(), "", ""
    reason = ""
    for detail in err.get("details", []) or []:
        if isinstance(detail, dict) and detail.get("reason"):
            reason = detail["reason"]
            break
    return str(err.get("message", "")).strip(), str(err.get("status", "")), reason


def map_http_error(resp: httpx.Response) -> ProviderError:
    code = resp.status_code
    message, status, reason = _error_info(resp)
    detail = message or status or resp.reason_phrase
    if code in (401, 403) or reason == "API_KEY_INVALID" or "API key not valid" in message:
        return ProviderError(f"Gemini rejected the API key ({detail})")
    if code == 429:
        return ProviderError(f"Rate limit or quota reached ({detail})", retryable=True)
    if code in RETRY_STATUS:
        return ProviderError(f"Gemini server error {code} ({detail})", retryable=True)
    return ProviderError(f"Gemini error {code}: {detail}")


def parse_response(payload: dict) -> list[OutputFile]:
    feedback = payload.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise ProviderError(f"Prompt blocked by Gemini safety filters ({feedback['blockReason']})")

    files: list[OutputFile] = []
    texts: list[str] = []
    reasons: list[str] = []
    for cand in payload.get("candidates") or []:
        if cand.get("finishReason"):
            reasons.append(cand["finishReason"])
        for part in (cand.get("content") or {}).get("parts") or []:
            if part.get("thought"):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                if not mime.startswith("image/"):
                    continue
                files.append(OutputFile(base64.b64decode(inline["data"]),
                                        EXT_BY_MIME.get(mime, mime.split("/")[-1])))
            elif part.get("text"):
                texts.append(part["text"].strip())
    if files:
        return files

    policy = [r for r in reasons if r in POLICY_REASONS]
    if policy:
        raise ProviderError(f"Image refused by content policy ({policy[0]})")
    reason = reasons[0] if reasons else "no candidates"
    note = f": {texts[0][:200]}" if texts else ""
    raise ProviderError(f"No image returned ({reason}){note}")
