"""OpenAI Images API (``/v1/images/generations`` and ``/v1/images/edits``).

Uses the official REST endpoints with the user's own key. Text-only rows go to
generations (JSON); rows with reference images go to edits (multipart, ``image[]``).
Images are saved exactly as returned.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Callable

import httpx

from src.gen.gemini_image import encode_ref
from src.gen.http_common import EXT_BY_MIME, download, json_body, map_http_error, send
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested

log = logging.getLogger(__name__)

API_BASE = "https://api.openai.com/v1"
KEY_ID = "openai"
WHO = "OpenAI"

MODELS = [
    "gpt-image-2.5-flare",
    "gpt-image-2.5-sunburst",
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1-mini",
]
STANDARD_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
# Custom sizes (multiples of 16, ratio 1:3..3:1, ≤ 3840x2160) only work on the 2.x models.
CUSTOM_SIZES = ["2048x2048", "2048x1152", "1152x2048", "2560x1440", "1440x2560", "3840x2160", "2160x3840"]
SIZES = STANDARD_SIZES + CUSTOM_SIZES
CUSTOM_SIZE_MODELS = ("gpt-image-2",)  # prefix: covers gpt-image-2 and gpt-image-2.5-*
QUALITIES = ["auto", "low", "medium", "high", "xhigh", "max"]
XHIGH_MODELS = ("gpt-image-2.5",)
FORMATS = ["png", "jpeg", "webp"]
BACKGROUNDS = ["auto", "opaque", "transparent"]
MODERATION = ["auto", "low"]

MAX_REFS = 16
MAX_N = 10


def _no_key_message() -> str:
    return "No OpenAI API key. Add one in Settings → API keys."


class OpenAIImageProvider(Provider):
    key = "openai_image"
    name = "OpenAI Images API"

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
            ConfigField("size", "gen_size", "choice", "auto", SIZES),
            ConfigField("quality", "gen_quality", "choice", "auto", QUALITIES),
            ConfigField("output_format", "gen_output_format", "choice", "png", FORMATS),
            ConfigField("background", "gen_background", "choice", "auto", BACKGROUNDS,
                        option_prefix="oai_bg_"),
            ConfigField("moderation", "gen_moderation", "choice", "auto", MODERATION,
                        option_prefix="oai_mod_"),
            ConfigField("timeout", "gen_timeout", "int", 180, minimum=10, maximum=900),
        ]

    # ---- request ----------------------------------------------------
    def build_params(self, prompt: str, options: dict[str, Any], n: int) -> dict[str, Any]:
        model = options.get("model") or MODELS[0]
        size = options.get("size") or "auto"
        if size not in STANDARD_SIZES and not model.startswith(CUSTOM_SIZE_MODELS):
            raise ProviderError(f"Size {size} needs a gpt-image-2 model; {model} only takes "
                                + ", ".join(STANDARD_SIZES))
        quality = options.get("quality") or "auto"
        if quality in ("xhigh", "max") and not model.startswith(XHIGH_MODELS):
            log.warning("%s has no '%s' quality; using 'high'", model, quality)
            quality = "high"
        fmt = options.get("output_format") or "png"
        background = options.get("background") or "auto"
        if background == "transparent" and fmt == "jpeg":
            log.warning("JPEG can't be transparent; saving PNG instead")
            fmt = "png"
        params: dict[str, Any] = {"model": model, "prompt": prompt, "n": n, "size": size,
                                  "quality": quality, "output_format": fmt}
        if background != "auto":
            params["background"] = background
        moderation = options.get("moderation") or "auto"
        if moderation != "auto":
            params["moderation"] = moderation
        return params

    def build_request(self, prompt: str, refs: list[Path], options: dict[str, Any],
                      n: int = 1) -> tuple[str, dict]:
        """Return (url, httpx kwargs): JSON for generations, multipart for edits."""
        params = self.build_params(prompt, options, n)
        if not refs:
            return f"{self.api_base}/images/generations", {"json": params}
        if len(refs) > MAX_REFS:
            log.warning("%d reference images; sending the first %d", len(refs), MAX_REFS)
        files = []
        for ref in refs[:MAX_REFS]:
            ref = Path(ref)
            mime, data = encode_ref(ref)
            name = ref.stem + "." + EXT_BY_MIME.get(mime, "png")
            files.append(("image[]", (name, base64.b64decode(data), mime)))
        form = {k: str(v) for k, v in params.items()}
        return f"{self.api_base}/images/edits", {"data": form, "files": files}

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        key = (self.key_source() or "").strip()
        if not key:
            raise ProviderError(_no_key_message())
        count = max(1, int(options.get("count", 1)))
        timeout = float(options.get("timeout", 180))
        outputs: list[OutputFile] = []
        ctx.progress(0.05)
        while len(outputs) < count:
            if ctx.should_stop():
                raise StopRequested()
            n = min(MAX_N, count - len(outputs))
            url, kwargs = self.build_request(job.prompt, job.refs, options, n)
            outputs.extend(self._call(url, kwargs, key, timeout, options))
            ctx.progress(min(1.0, len(outputs) / count))
        return outputs

    def _call(self, url: str, kwargs: dict, key: str, timeout: float,
              options: dict[str, Any]) -> list[OutputFile]:
        headers = {"Authorization": f"Bearer {key}"}
        resp = send(lambda: self._client.post(url, headers=headers, timeout=timeout, **kwargs))
        if resp.status_code != 200:
            raise map_http_error(resp, WHO)
        payload = json_body(resp, WHO)
        ext = payload.get("output_format") or options.get("output_format") or "png"
        return self.parse_response(payload, ext)

    def parse_response(self, payload: dict, ext: str = "png") -> list[OutputFile]:
        ext = "jpg" if ext == "jpeg" else ext
        files = []
        for item in payload.get("data") or []:
            if item.get("b64_json"):
                files.append(OutputFile(base64.b64decode(item["b64_json"]), ext))
            elif item.get("url"):
                files.append(OutputFile(download(self._client, item["url"], WHO), ext))
        if not files:
            raise ProviderError("OpenAI returned no image")
        return files

    def close(self) -> None:
        self._client.close()
