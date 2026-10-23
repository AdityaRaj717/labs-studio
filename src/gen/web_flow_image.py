"""Google Flow image generation through the google-flow MCP server.

Uses the Flow web app (flow.google.com) in the user's signed-in Chrome with
their own Google AI Pro subscription instead of an API key. The browser work is
done by the google-flow MCP (``src/web/flow_mcp.py``); this provider adds the
app's pacing: one job at a time, a random gap between jobs and a daily cap
(Settings → Web Sessions). A sign-in wall, CAPTCHA or limit message stops the
whole queue and brings the Chrome window to the front.
"""

from __future__ import annotations

import concurrent.futures
import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from src.characters.flow_sync import SyncError
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested
from src.web.adapters.base import BLOCK_MESSAGES, load_selectors
from src.web.mcp_client import McpError, McpToolError

log = logging.getLogger(__name__)

SITE = "flow"
SITE_TITLE = "Google Flow"

# MCP error code -> how the queue treats it.
BLOCK_CODES = {
    "NOT_LOGGED_IN": "login", "WRONG_GOOGLE_ACCOUNT": "login",
    "MANUAL_VERIFICATION_REQUIRED": "captcha", "GOOGLE_LIMIT_REACHED": "quota",
}
STOP_CODES = {  # every later job would fail the same way
    "UNKNOWN_UI_CHANGE", "GENERATION_BUTTON_DISABLED", "MODEL_NOT_AVAILABLE",
    "RATIO_NOT_AVAILABLE", "INVALID_PARAMS", "PROJECT_NOT_FOUND",
}
JOB_CODES = {"GENERATION_REFUSED"}  # only this prompt failed
# Codes raised after the prompt was sent, so the attempt counts towards the daily cap.
SUBMITTED_CODES = {"GENERATION_REFUSED", "GENERATION_TIMEOUT", "DOWNLOAD_FAILED"}


def _flow_options() -> tuple[list[str], list[str], int]:
    image = load_selectors(SITE).get("image", {})
    return list(image.get("models", {})), list(image.get("aspects", {})), int(image.get("max_count", 4))


class WebFlowImageProvider(Provider):
    key = "web_flow_image"
    name = "Google Flow web (image)"
    site = SITE

    def __init__(self, backend=None, pacer=None, session=None, out_root: Path | None = None):
        self._backend = backend
        self._session = session
        if pacer is None:
            from src.web.pacing import Pacer

            pacer = Pacer(SITE)
        self.pacer = pacer
        self.out_root = out_root
        self._lock = threading.Lock()

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
        models, aspects, _ = _flow_options()
        return [
            ConfigField("model", "gen_model", "choice", models[0], models),
            ConfigField("aspect", "gen_aspect", "choice", aspects[0], aspects),
            ConfigField("download_size", "gen_image_size", "choice", "1K", ["1K", "2K"]),
            ConfigField("timeout", "gen_timeout", "int", 300, minimum=60, maximum=900),
        ]

    def _out_dir(self, job: Job) -> Path:
        root = self.out_root
        if root is None:
            from src import config

            root = Path(config.get("web.diag_dir", r"D:\glabs_web\diag")).parent / "flow_tmp"
        return root / f"{datetime.now():%Y%m%d-%H%M%S}-job{job.id}"

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        timeout = float(options.get("timeout", 300))
        _, _, max_count = _flow_options()
        # Library characters and scenes go to Flow by name (set up in its Characters
        # section first), so their images are not uploaded as loose references.
        from src.characters.attach import character_ids

        chars, scenes = character_ids(job), list(job.scenes)
        library = set(job.character_refs) | set(job.scene_refs)
        refs = [r for r in job.refs if r not in library] if chars or scenes else list(job.refs)
        args = {
            "prompt": job.prompt,
            "model": options.get("model") or None,
            "ratio": options.get("aspect") or "1:1",
            "count": max(1, min(int(options.get("count", 1)), max_count)),
            "download_size": options.get("download_size") or "1K",
            "reference_images": [str(Path(r).resolve()) for r in refs],
            "filename": "img",
        }
        args = {k: v for k, v in args.items() if v not in (None, [])}
        with self._lock:
            if self.pacer.cap_reached():
                raise ProviderError(
                    f"Daily cap for {SITE_TITLE} reached ({self.pacer.cap} prompts). "
                    "Raise it in Settings → Web Sessions or try tomorrow.", stop_queue=True)
            if not self.pacer.wait_turn(ctx.should_stop):
                raise StopRequested()
            ctx.progress(0.05)
            out = self._out_dir(job)
            args["output_folder"] = str(out)
            try:
                extra = {"characters": chars, "scenes": scenes} if chars or scenes else {}
                result = self.backend.generate_image(args, timeout, **extra)
                used = self.pacer.record_use()
                log.info("%s: job %d done via MCP (%d today): %s", SITE_TITLE, job.index, used,
                         str(result.get("agent_reply", ""))[:120])
                files = self._read_files(result)
            except McpToolError as exc:
                if exc.code in SUBMITTED_CODES:
                    self.pacer.record_use()
                raise self._map_error(exc) from None
            except McpError as exc:
                raise ProviderError(f"Google Flow MCP server problem: {exc}. Check the MCP folder in "
                                    "Settings → Web Sessions.", stop_queue=True) from None
            except concurrent.futures.TimeoutError:
                raise ProviderError(f"{SITE_TITLE} MCP did not answer in time", retryable=True) from None
            except ProviderError:
                raise
            except SyncError as exc:
                raise ProviderError(f"{SITE_TITLE}: {exc}") from None
            except Exception as exc:  # noqa: BLE001 - e.g. Chrome could not be launched
                raise ProviderError(f"{type(exc).__name__}: {exc}", stop_queue=True) from None
            finally:
                self.pacer.mark_done()
                shutil.rmtree(out, ignore_errors=True)
        ctx.progress(1.0)
        return files

    def _read_files(self, result: dict[str, Any]) -> list[OutputFile]:
        if result.get("status") != "success":
            raise ProviderError(f"{SITE_TITLE} MCP returned status {result.get('status')!r}: "
                                f"{result.get('message', '')}", retryable=True)
        files = []
        for f in result.get("files") or []:
            p = Path(f)
            ext = p.suffix.lstrip(".").lower() or "jpg"
            files.append(OutputFile(p.read_bytes(), "jpg" if ext == "jpeg" else ext))
        if not files:
            raise ProviderError(f"{SITE_TITLE} finished but no image was downloaded", retryable=True)
        return files

    def _map_error(self, exc: McpToolError) -> ProviderError:
        code, msg = exc.code, str(exc)
        if code in BLOCK_CODES:
            self.session.bring_to_front(SITE)
            return ProviderError(BLOCK_MESSAGES[BLOCK_CODES[code]].format(site=SITE_TITLE), stop_queue=True)
        if code in STOP_CODES:
            if code == "UNKNOWN_UI_CHANGE":
                self.session.bring_to_front(SITE)
            return ProviderError(f"{SITE_TITLE}: {msg} ({code})", stop_queue=True)
        if code in JOB_CODES:
            return ProviderError(f"{SITE_TITLE} refused the prompt: {msg}")
        return ProviderError(f"{SITE_TITLE}: {msg}" + (f" ({code})" if code else ""), retryable=True)
