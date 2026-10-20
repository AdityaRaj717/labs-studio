"""Gemini API video generation with Gemini Omni Flash (Interactions API).

Uses the official REST endpoint with the user's own key. Veo 3.1 Preview shuts
down on 2026-10-22, so it isn't offered (see docs/phase-04-gemini-video.md).
Videos come back with Google's SynthID watermark and are saved unchanged.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from src.gen.gemini_image import KEY_ID, _no_key_message, encode_ref, map_http_error
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

MODELS = ["gemini-omni-1.1-flash"]
ASPECTS = ["16:9", "9:16"]
RESOLUTIONS = ["360p", "720p", "1080p", "4k"]
DURATIONS = ["auto", "4", "6", "8", "10"]
TASKS = ["auto", "text_to_video", "image_to_video", "reference_to_video"]

MAX_FRAMES = 2       # start frame, end frame
MAX_REFERENCES = 3   # subject references (reference_to_video)
EXPECTED_SECONDS = 120.0
POLL_SLICE = 0.5
MAX_POLL_FAILURES = 3

PENDING = {"queued", "in_progress"}
POLICY_RE = re.compile(r"\b(safety|policy|policies|blocked|prohibited|rai|filtered|responsible ai)\b",
                       re.IGNORECASE)
RETRY_STATUS = {429, 500, 502, 503, 504}
EXT_BY_MIME = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}


class GeminiVideoProvider(Provider):
    key = "gemini_video"
    name = "Gemini API (video)"

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
            ConfigField("model", "gen_model", "choice", MODELS[0], MODELS),
            ConfigField("aspect", "gen_aspect", "choice", "16:9", ASPECTS),
            ConfigField("resolution", "gen_resolution", "choice", "720p", RESOLUTIONS),
            ConfigField("duration", "gen_duration", "choice", "auto", DURATIONS,
                        option_prefix="vid_duration_"),
            ConfigField("task", "gen_video_task", "choice", "auto", TASKS, option_prefix="vid_task_"),
            ConfigField("poll_interval", "gen_poll_interval", "int", 10, minimum=2, maximum=60),
            ConfigField("timeout", "gen_job_timeout", "int", 600, minimum=60, maximum=1800),
        ]

    # ---- request ----------------------------------------------------
    def build_request(self, prompt: str, refs: list[Path], options: dict[str, Any]) -> tuple[str, dict]:
        task = options.get("task") or "auto"
        duration = str(options.get("duration") or "auto")
        text = prompt.strip()
        if duration != "auto":
            text = f"{text.rstrip('.')}. Make the clip about {duration} seconds long."

        limit = MAX_REFERENCES if task == "reference_to_video" else MAX_FRAMES
        if task == "text_to_video":
            limit = 0
        if len(refs) > limit:
            log.warning("%d reference image(s); sending the first %d for %s", len(refs), limit, task)
        images = []
        for ref in refs[:limit]:
            mime, data = encode_ref(Path(ref))
            images.append({"type": "image", "data": data, "mime_type": mime})

        body: dict[str, Any] = {
            "model": options.get("model") or MODELS[0],
            "input": images + [{"type": "text", "text": text}] if images else text,
            "response_format": {
                "type": "video",
                "aspect_ratio": options.get("aspect") or "16:9",
                "resolution": options.get("resolution") or "720p",
            },
            "background": True,
            "store": True,
        }
        if task != "auto":
            body["generation_config"] = {"video_config": {"task": task}}
        return f"{self.api_base}/interactions", body

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        key = (self.key_source() or "").strip()
        if not key:
            raise ProviderError(_no_key_message())
        count = max(1, int(options.get("count", 1)))
        url, body = self.build_request(job.prompt, job.refs, options)
        outputs: list[OutputFile] = []
        for n in range(count):
            if ctx.should_stop():
                raise StopRequested()

            def part(p: float, n=n) -> None:
                ctx.progress((n + p) / count)

            outputs.extend(self._one(url, body, key, options, ctx, part))
        return outputs

    def _one(self, url: str, body: dict, key: str, options: dict, ctx: RunContext,
             progress: Callable[[float], None]) -> list[OutputFile]:
        timeout = float(options.get("timeout", 600))
        interval = max(0.1, float(options.get("poll_interval", 10)))
        headers = {"x-goog-api-key": key}
        start = self.clock()
        progress(0.02)
        resp = self._send(lambda: self._client.post(url, json=body, headers=headers, timeout=60))
        if resp.status_code == 400 and "background" in resp.text.lower():
            log.info("Server refused background mode; sending a synchronous request")
            sync = body | {"background": False, "store": False}
            resp = self._send(lambda: self._client.post(url, json=sync, headers=headers, timeout=timeout))
        if resp.status_code != 200:
            raise map_http_error(resp)
        data = _json(resp)
        progress(0.05)

        failures = 0
        while data.get("status") in PENDING:
            op_id = data.get("id") or ""
            if not op_id:
                raise ProviderError("Gemini returned a pending interaction without an id")
            self._wait(interval, ctx, start, timeout, op_id, headers)
            elapsed = self.clock() - start
            progress(0.05 + 0.85 * min(elapsed / EXPECTED_SECONDS, 1.0))
            try:
                poll = self._client.get(f"{self.api_base}/interactions/{op_id}",
                                        headers=headers, timeout=60)
            except httpx.HTTPError as exc:
                failures = self._poll_failed(failures, f"network error {type(exc).__name__}")
                continue
            if poll.status_code in RETRY_STATUS:
                failures = self._poll_failed(failures, f"HTTP {poll.status_code}")
                continue
            if poll.status_code != 200:
                raise map_http_error(poll)
            failures = 0
            data = _json(poll)

        progress(0.95)
        files = self._collect(parse_interaction(data), headers)
        progress(1.0)
        return files

    def _send(self, call: Callable[[], httpx.Response]) -> httpx.Response:
        try:
            return call()
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Network timeout: {type(exc).__name__}", retryable=True) from None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error: {type(exc).__name__}", retryable=True) from None

    @staticmethod
    def _poll_failed(failures: int, what: str) -> int:
        failures += 1
        log.warning("Polling the video job failed (%s), attempt %d/%d", what, failures, MAX_POLL_FAILURES)
        if failures >= MAX_POLL_FAILURES:
            # Not retryable: the job was already submitted (and billed); resubmitting pays twice.
            raise ProviderError(f"Lost contact with the running video job ({what})")
        return failures

    def _wait(self, interval: float, ctx: RunContext, start: float, timeout: float,
              op_id: str, headers: dict) -> None:
        waited = 0.0
        while waited < interval:
            if ctx.should_stop():
                self._cancel(op_id, headers)
                raise StopRequested()
            if self.clock() - start > timeout:
                self._cancel(op_id, headers)
                raise ProviderError(f"Video job timed out after {int(timeout)} s")
            step = min(POLL_SLICE, interval - waited)
            self.sleep(step)
            waited += step

    def _cancel(self, op_id: str, headers: dict) -> None:
        try:
            self._client.post(f"{self.api_base}/interactions/{op_id}/cancel", headers=headers, timeout=15)
        except httpx.HTTPError:
            log.info("Cancel request for the video job failed (ignored)")

    def _collect(self, items: list[dict], headers: dict) -> list[OutputFile]:
        files = []
        for item in items:
            mime = item.get("mime_type") or item.get("mimeType") or "video/mp4"
            ext = EXT_BY_MIME.get(mime, "mp4")
            if item.get("data"):
                files.append(OutputFile(base64.b64decode(item["data"]), ext))
                continue
            files.append(OutputFile(self._download(item["uri"], headers), ext))
        return files

    def _download(self, uri: str, headers: dict) -> bytes:
        """GET the video, following redirects by hand: the key only goes to the API host."""
        api_host = httpx.URL(self.api_base).host
        url = httpx.URL(uri)
        for _ in range(6):
            send = headers if url.host == api_host else {}
            resp = self._send(lambda: self._client.get(url, headers=send, timeout=300))
            if resp.is_redirect and resp.headers.get("location"):
                url = url.join(resp.headers["location"])
                continue
            if resp.status_code != 200:
                raise map_http_error(resp)
            return resp.content
        raise ProviderError("Too many redirects while downloading the video")

    def close(self) -> None:
        self._client.close()


# ---- helpers (module level so tests can hit them directly) ------------
def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise ProviderError("Gemini returned a response that isn't JSON", retryable=True) from None
    if not isinstance(data, dict):
        raise ProviderError("Gemini returned an unexpected response")
    return data


def _content_items(data: dict):
    for step in data.get("steps") or []:
        if isinstance(step, dict) and step.get("type") == "model_output":
            yield from step.get("content") or []
    yield from data.get("outputs") or []


def parse_interaction(data: dict) -> list[dict]:
    """Video content items ({data|uri, mime_type}) of a finished interaction, or raise."""
    status = data.get("status") or ""
    if status == "failed":
        errors = data.get("errors") or ([data["error"]] if isinstance(data.get("error"), dict) else [])
        err = errors[0] if errors else {}
        message = str(err.get("message") or "no details").strip()
        code = str(err.get("code") or "")
        if POLICY_RE.search(f"{message} {code}"):
            raise ProviderError(f"Video refused by content policy ({message[:200]})")
        raise ProviderError(f"Video generation failed: {message[:200]}")
    if status == "cancelled":
        raise ProviderError("Video job was cancelled on the server")
    if status == "requires_action":
        raise ProviderError("Gemini asked for an action this app doesn't support (requires_action)")

    videos, texts = [], []
    for item in _content_items(data):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "video" and (item.get("data") or item.get("uri")):
            videos.append(item)
        elif item.get("type") == "text" and item.get("text"):
            texts.append(item["text"].strip())
    if videos:
        return videos
    note = f": {texts[0][:200]}" if texts else ""
    if texts and POLICY_RE.search(texts[0]):
        raise ProviderError(f"Video refused by content policy{note}")
    raise ProviderError(f"No video returned ({status or 'no status'}){note}")
