"""Google Flow image generation through the shared engine.

Uses the Flow web app in the user's signed-in Chrome with their own Google AI Pro
subscription instead of an API key. The engine (``src/web/flow_mcp.py``) does the browser
work and the pacing, and keeps each result in a permanent run folder. A sign-in wall, CAPTCHA
or limit stops the whole queue and brings the Chrome window to the front.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from src.characters.flow_sync import SyncError
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Estimate, Provider, ProviderError, RunContext
from src.web.engine_client import EngineError, EngineToolError

log = logging.getLogger(__name__)

SITE = "flow"
SITE_TITLE = "Google Flow"

BLOCK_MESSAGES = {
    "captcha": "{site} is showing a CAPTCHA or bot check. Solve it yourself in the Chrome window, then start again.",
    "login": "{site} wants you to sign in. Sign in by hand in the Chrome window (Settings → Web Sessions → Launch browser), then start again.",
    "quota": "{site} says the usage limit is reached. The queue was stopped; try again later.",
}
# Engine error code -> how the queue treats it.
BLOCK_CODES = {
    "NOT_LOGGED_IN": "login", "WRONG_GOOGLE_ACCOUNT": "login",
    "MANUAL_VERIFICATION_REQUIRED": "captcha", "WAF_BLOCK": "captcha",
    "GOOGLE_LIMIT_REACHED": "quota", "DAILY_MODEL_LIMIT": "quota",
}
STOP_CODES = {  # every later job would fail the same way
    "UNKNOWN_UI_CHANGE", "GENERATION_BUTTON_DISABLED", "MODEL_NOT_AVAILABLE", "RATIO_NOT_AVAILABLE",
    "INVALID_PARAMS", "PROJECT_NOT_FOUND", "COMBINATION_NOT_SUPPORTED", "BROWSER_NOT_CONNECTED",
    "FLOW_PAGE_NOT_FOUND", "DAILY_CAP_REACHED", "BUDGET_EXCEEDED",
}
JOB_CODES = {"GENERATION_REFUSED", "SAFETY_BLOCKED"}  # only this prompt failed


def capabilities() -> dict[str, Any]:
    """What ``flow_capabilities`` answers, from the engine's own file: pages are built on the
    GUI thread, which must not wait for an engine to start."""
    from src.web.flow_mcp import flow_mcp

    return json.loads((flow_mcp().mcp_dir / "config" / "capabilities.json").read_text(encoding="utf-8"))


def map_engine_error(exc: EngineToolError, session) -> ProviderError:
    code, msg = exc.code, str(exc)
    if code in BLOCK_CODES:
        session.bring_to_front(SITE)
        return ProviderError(BLOCK_MESSAGES[BLOCK_CODES[code]].format(site=SITE_TITLE), stop_queue=True)
    if code in STOP_CODES:
        if code == "UNKNOWN_UI_CHANGE":
            session.bring_to_front(SITE)
        return ProviderError(f"{SITE_TITLE}: {msg} ({code})", stop_queue=True)
    if code in JOB_CODES:
        return ProviderError(f"{SITE_TITLE} refused the prompt: {msg}")
    # The engine says what may repeat: past the credit line another try spends again.
    return ProviderError(f"{SITE_TITLE}: {msg}" + (f" ({code})" if code else ""),
                         retryable=bool(exc.payload.get("retryable")))


def report_event(event: dict[str, Any], ctx: RunContext) -> None:
    """Show an engine job event on the row: only ``source: flow`` is Flow's own percent."""
    if event.get("type") == "job.progress":
        if event.get("progress") is not None:
            ctx.note(str(event.get("source") or ""))
            ctx.progress(float(event["progress"]) / 100)
        if event.get("previewPath"):
            ctx.partial(Path(event["previewPath"]))
    elif event.get("type") == "job.transition":
        ctx.note("phase")


def read_outputs(view: dict[str, Any], what: str) -> list[OutputFile]:
    files = []
    for output in view.get("outputs") or []:
        path = Path(output["file"])
        ext = path.suffix.lstrip(".").lower() or "jpg"
        files.append(OutputFile(path.read_bytes(), "jpg" if ext == "jpeg" else ext))
    if not files:
        raise ProviderError(f"{SITE_TITLE} finished but no {what} was downloaded")
    return files


def run_engine_job(provider, job: Job, tool: str, args: dict[str, Any], timeout: float, ctx: RunContext,
                   what: str) -> list[OutputFile]:
    """One job through the engine, keyed so a repeat after a crash or timeout spends nothing."""
    from src.characters.attach import character_ids

    job.engine_key = job.engine_key or f"app:{uuid.uuid4()}"
    chars, scenes = character_ids(job), list(job.scenes)
    extra = {"characters": chars, "scenes": scenes} if chars or scenes else {}
    ctx.note("phase")
    ctx.progress(0.05)
    try:
        view = provider.backend.run_job(tool, {**args, "idempotency_key": job.engine_key}, timeout,
                                        on_event=lambda e: report_event(e, ctx), should_stop=ctx.should_stop, **extra)
        files = read_outputs(view, what)
    except TimeoutError:  # still running in the engine: the key picks it up again
        raise ProviderError(f"{SITE_TITLE} did not finish in time", retryable=True) from None
    except EngineToolError as exc:
        job.engine_key = ""
        raise map_engine_error(exc, provider.session) from None
    except EngineError as exc:
        raise ProviderError(f"Google Flow engine problem: {exc}. Check the MCP folder in "
                            "Settings → Web Sessions.", stop_queue=True) from None
    except SyncError as exc:
        job.engine_key = ""
        raise ProviderError(f"{SITE_TITLE}: {exc}") from None
    job.engine_key = ""
    ctx.progress(1.0)
    return files


class WebFlowImageProvider(Provider):
    key = "web_flow_image"
    name = "Google Flow web (image)"
    site = SITE
    max_count = 4

    def __init__(self, backend=None, session=None):
        self._backend = backend
        self._session = session

    def estimate(self, jobs: list[Job], options: dict[str, Any]) -> Estimate:
        return Estimate(len(jobs), capabilities()["image"]["credits"], "gen_estimate_quota")

    @property
    def backend(self):
        if self._backend is None:
            from src.web.flow_mcp import flow_mcp

            self._backend = flow_mcp()
        return self._backend

    @property
    def session(self):
        if self._session is None:
            from src.web.session import session

            self._session = session()
        return self._session

    def config_fields(self) -> list[ConfigField]:
        image = capabilities()["image"]
        return [
            ConfigField("model", "gen_model", "choice", image["defaultModel"], image["models"], option_prefix="flow_model_"),
            ConfigField("aspect", "gen_aspect", "choice", "1:1", ["1:1", "16:9", "9:16", "4:3", "3:4"]),
            ConfigField("download_size", "gen_image_size", "choice", image["sizes"][0], image["sizes"]),
            ConfigField("timeout", "gen_timeout", "int", 300, minimum=60, maximum=900),
        ]

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        # Library characters and scenes go to Flow by name (set up in its Characters
        # section first), so their images are not uploaded as loose references.
        library = set(job.character_refs) | set(job.scene_refs)
        refs = [r for r in job.refs if r not in library]
        args = {
            "prompt": job.prompt,
            "model": options.get("model") or None,
            "ratio": options.get("aspect") or "1:1",
            "count": max(1, int(options.get("count", 1))),
            "size": options.get("download_size") or "1K",
            "ingredients": [str(Path(r).resolve()) for r in refs],
        }
        args = {k: v for k, v in args.items() if v not in (None, [])}
        return run_engine_job(self, job, "flow_generate_image", args, float(options.get("timeout", 300)), ctx, "image")
