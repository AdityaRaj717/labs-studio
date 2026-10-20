"""xAI Grok Imagine: images (generations / edits) and video (async generations).

Uses the official REST API (``https://api.x.ai/v1``) with the user's own key.
Image mode: text-only rows → ``images/generations``; rows with refs →
``images/edits`` (1 ref = ``image``, more = ``images``). Video mode →
``videos/generations``, then poll ``GET videos/{request_id}`` and download the
temporary URL. Files are saved exactly as returned.
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from src.gen.gemini_image import encode_ref
from src.gen.http_common import (
    EXT_BY_MIME, POLICY_RE, RETRY_STATUS, download, json_body, map_http_error, send,
)
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested

log = logging.getLogger(__name__)

API_BASE = "https://api.x.ai/v1"
KEY_ID = "xai"
WHO = "xAI"

MODES = ["image", "video"]
IMAGE_MODELS = ["grok-imagine-image-2.0", "grok-imagine-image-quality", "grok-imagine-image"]
VIDEO_MODELS = ["grok-imagine-video-1.5", "grok-imagine-video-1.5-lite", "grok-imagine-video"]
ASPECTS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "5:2"]
IMAGE_RESOLUTIONS = ["1k", "2k"]
IMAGE_QUALITIES = ["auto", "low", "medium"]
QUALITY_MODELS = {"grok-imagine-image-2.0"}
VIDEO_RESOLUTIONS = ["480p", "720p", "1080p"]
VIDEO_REFS = ["auto", "start_frame", "references"]

MAX_EDIT_REFS = 5
MAX_VIDEO_REFS = 14
MAX_N = 10
EXPECTED_SECONDS = 90.0
POLL_SLICE = 0.5
MAX_POLL_FAILURES = 3
PENDING = {"pending", "queued", "in_progress", "processing"}


def _no_key_message() -> str:
    return "No xAI API key. Add one in Settings → API keys."


def data_uri(path: Path) -> str:
    mime, data = encode_ref(Path(path))
    return f"data:{mime};base64,{data}"


class GrokProvider(Provider):
    key = "grok"
    name = "xAI Grok Imagine"

    def __init__(self, key_source: Callable[[], str] | None = None,
                 transport: httpx.BaseTransport | None = None, api_base: str = API_BASE,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if key_source is None:
            from src.keys import get_key

            key_source = lambda: get_key(KEY_ID)  # noqa: E731
        self.key_source = key_source
        self.api_base = api_base.rstrip("/")
        self.sleep = sleep
        self.clock = clock
        self._client = httpx.Client(transport=transport)

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField("mode", "gen_mode", "choice", "image", MODES, option_prefix="grok_mode_"),
            ConfigField("image_model", "gen_image_model", "choice", IMAGE_MODELS[0], IMAGE_MODELS),
            ConfigField("video_model", "gen_video_model", "choice", VIDEO_MODELS[0], VIDEO_MODELS),
            ConfigField("aspect", "gen_aspect", "choice", "auto", ASPECTS),
            ConfigField("image_resolution", "gen_image_resolution", "choice", "1k", IMAGE_RESOLUTIONS),
            ConfigField("image_quality", "gen_image_quality", "choice", "auto", IMAGE_QUALITIES),
            ConfigField("video_resolution", "gen_video_resolution", "choice", "720p", VIDEO_RESOLUTIONS),
            ConfigField("video_duration", "gen_video_seconds", "int", 8, minimum=1, maximum=15),
            ConfigField("video_audio", "gen_video_audio", "bool", True),
            ConfigField("video_refs", "gen_video_refs", "choice", "auto", VIDEO_REFS,
                        option_prefix="grok_refs_"),
            ConfigField("poll_interval", "gen_poll_interval", "int", 5, minimum=2, maximum=60),
            ConfigField("timeout", "gen_job_timeout", "int", 600, minimum=60, maximum=1800),
        ]

    # ---- requests ---------------------------------------------------
    def build_image_request(self, prompt: str, refs: list[Path], options: dict[str, Any],
                            n: int = 1) -> tuple[str, dict]:
        model = options.get("image_model") or IMAGE_MODELS[0]
        body: dict[str, Any] = {"model": model, "prompt": prompt, "n": n,
                                "response_format": "b64_json",
                                "resolution": options.get("image_resolution") or "1k"}
        aspect = options.get("aspect") or "auto"
        if aspect != "auto":
            body["aspect_ratio"] = aspect
        quality = options.get("image_quality") or "auto"
        if quality != "auto" and model in QUALITY_MODELS:
            body["quality"] = quality
        if not refs:
            return f"{self.api_base}/images/generations", body
        if len(refs) > MAX_EDIT_REFS:
            log.warning("%d reference images; sending the first %d", len(refs), MAX_EDIT_REFS)
        images = [{"url": data_uri(r)} for r in refs[:MAX_EDIT_REFS]]
        if len(images) == 1:
            body["image"] = images[0]
        else:
            body["images"] = images
        return f"{self.api_base}/images/edits", body

    def build_video_request(self, prompt: str, refs: list[Path],
                            options: dict[str, Any]) -> tuple[str, dict]:
        body: dict[str, Any] = {
            "model": options.get("video_model") or VIDEO_MODELS[0],
            "duration": int(options.get("video_duration", 8)),
            "resolution": options.get("video_resolution") or "720p",
        }
        if prompt.strip():
            body["prompt"] = prompt
        aspect = options.get("aspect") or "auto"
        if aspect != "auto":
            body["aspect_ratio"] = aspect
        if not options.get("video_audio", True):
            body["generate_audio"] = False
        how = options.get("video_refs") or "auto"
        if refs:
            if how == "start_frame" or (how == "auto" and len(refs) == 1):
                if len(refs) > 1:
                    log.warning("%d refs; only the first is used as the start frame", len(refs))
                body["image"] = {"url": data_uri(refs[0])}
            else:
                if len(refs) > MAX_VIDEO_REFS:
                    log.warning("%d reference images; sending the first %d", len(refs), MAX_VIDEO_REFS)
                body["reference_images"] = [{"url": data_uri(r)} for r in refs[:MAX_VIDEO_REFS]]
        return f"{self.api_base}/videos/generations", body

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        key = (self.key_source() or "").strip()
        if not key:
            raise ProviderError(_no_key_message())
        headers = {"Authorization": f"Bearer {key}"}
        count = max(1, int(options.get("count", 1)))
        if (options.get("mode") or "image") == "video":
            return self._videos(job, options, ctx, headers, count)
        return self._images(job, options, ctx, headers, count)

    def _images(self, job: Job, options: dict, ctx: RunContext, headers: dict,
                count: int) -> list[OutputFile]:
        timeout = float(options.get("timeout", 600))
        outputs: list[OutputFile] = []
        ctx.progress(0.05)
        while len(outputs) < count:
            if ctx.should_stop():
                raise StopRequested()
            n = min(MAX_N, count - len(outputs))
            url, body = self.build_image_request(job.prompt, job.refs, options, n)
            resp = send(lambda: self._client.post(url, json=body, headers=headers, timeout=timeout))
            if resp.status_code != 200:
                raise map_http_error(resp, WHO)
            outputs.extend(self.parse_images(json_body(resp, WHO)))
            ctx.progress(min(1.0, len(outputs) / count))
        return outputs

    def parse_images(self, payload: dict) -> list[OutputFile]:
        files = []
        for item in payload.get("data") or []:
            ext = EXT_BY_MIME.get(item.get("mime_type") or "", "jpg")
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
                if not item.get("mime_type"):
                    ext = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
                files.append(OutputFile(raw, ext))
            elif item.get("url"):
                files.append(OutputFile(download(self._client, item["url"], WHO), ext))
        if not files:
            raise ProviderError("xAI returned no image")
        return files

    def _videos(self, job: Job, options: dict, ctx: RunContext, headers: dict,
                count: int) -> list[OutputFile]:
        url, body = self.build_video_request(job.prompt, job.refs, options)
        outputs: list[OutputFile] = []
        for n in range(count):
            if ctx.should_stop():
                raise StopRequested()

            def part(p: float, n=n) -> None:
                ctx.progress((n + p) / count)

            outputs.append(self._one_video(url, body, headers, options, ctx, part))
        return outputs

    def _one_video(self, url: str, body: dict, headers: dict, options: dict, ctx: RunContext,
                   progress: Callable[[float], None]) -> OutputFile:
        timeout = float(options.get("timeout", 600))
        interval = max(0.1, float(options.get("poll_interval", 5)))
        start = self.clock()
        progress(0.02)
        resp = send(lambda: self._client.post(url, json=body, headers=headers, timeout=60))
        if resp.status_code not in (200, 201, 202):
            raise map_http_error(resp, WHO)
        request_id = json_body(resp, WHO).get("request_id")
        if not request_id:
            raise ProviderError("xAI accepted the video job but returned no request_id")
        log.info("xAI video job %s submitted", request_id)
        progress(0.05)

        failures = 0
        while True:
            self._wait(interval, ctx, start, timeout, request_id)
            try:
                poll = self._client.get(f"{self.api_base}/videos/{request_id}",
                                        headers=headers, timeout=60)
            except httpx.HTTPError as exc:
                failures = self._poll_failed(failures, f"network error {type(exc).__name__}")
                continue
            if poll.status_code in RETRY_STATUS:
                failures = self._poll_failed(failures, f"HTTP {poll.status_code}")
                continue
            if poll.status_code not in (200, 202):
                raise map_http_error(poll, WHO)
            failures = 0
            data = json_body(poll, WHO)
            status = str(data.get("status") or "pending").lower()
            if status in PENDING:
                pct = data.get("progress")
                if isinstance(pct, (int, float)):
                    progress(0.05 + 0.85 * min(max(pct, 0), 100) / 100)
                else:
                    elapsed = self.clock() - start
                    progress(0.05 + 0.85 * min(elapsed / EXPECTED_SECONDS, 1.0))
                continue
            break

        progress(0.95)
        video_url = parse_video(data)
        out = OutputFile(download(self._client, video_url, WHO), "mp4")
        progress(1.0)
        return out

    @staticmethod
    def _poll_failed(failures: int, what: str) -> int:
        failures += 1
        log.warning("Polling the xAI video job failed (%s), attempt %d/%d", what, failures,
                    MAX_POLL_FAILURES)
        if failures >= MAX_POLL_FAILURES:
            # Not retryable: the job was already submitted (and billed); resubmitting pays twice.
            raise ProviderError(f"Lost contact with the running video job ({what})")
        return failures

    def _wait(self, interval: float, ctx: RunContext, start: float, timeout: float,
              request_id: str) -> None:
        waited = 0.0
        while waited < interval:
            if ctx.should_stop():
                # xAI documents no cancel endpoint: the job finishes (and bills) server-side.
                log.info("Stopped polling xAI video job %s; it may still finish on xAI's side",
                         request_id)
                raise StopRequested()
            if self.clock() - start > timeout:
                raise ProviderError(f"Video job timed out after {int(timeout)} s")
            step = min(POLL_SLICE, interval - waited)
            self.sleep(step)
            waited += step

    def close(self) -> None:
        self._client.close()


def parse_video(data: dict) -> str:
    """Return the video URL from a finished poll, or raise with the reason."""
    status = str(data.get("status") or "").lower()
    video = data.get("video") or {}
    if status == "done" and video.get("url"):
        return video["url"]
    err = data.get("error") or {}
    if isinstance(err, str):
        err = {"message": err}
    message = str(err.get("message") or "").strip()
    code = str(err.get("code") or "")
    if status == "done" and video.get("respect_moderation") is False:
        raise ProviderError("Video refused by xAI content moderation")
    if POLICY_RE.search(f"{message} {code}"):
        raise ProviderError(f"Video refused by xAI content policy ({message or code})")
    if status == "expired":
        raise ProviderError("xAI video job expired before it finished")
    if status == "failed":
        detail = message or code or "no reason given"
        # The job ran and failed; only service-side failures are worth an automatic retry.
        retry = code in ("service_unavailable", "internal_error")
        raise ProviderError(f"xAI video job failed ({detail})", retryable=retry)
    raise ProviderError(f"xAI video job ended without a video (status '{status or 'unknown'}')")
