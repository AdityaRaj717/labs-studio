"""Google Flow image generation through the user's signed-in Chrome.

Uses the web app (labs.google/fx/tools/flow) with the user's own Google AI Pro
subscription instead of an API key. One job at a time, a random gap between
jobs and a daily cap (Settings → Web Sessions). A sign-in wall, CAPTCHA or limit
message stops the whole queue and brings the Chrome window to the front.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable

from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested
from src.web.adapters.base import BLOCK_MESSAGES, GenerationRefused, SiteBlocked, UiChanged

log = logging.getLogger(__name__)

SITE = "flow"
SITE_TITLE = "Google Flow"


def _flow_options() -> tuple[list[str], list[str], int]:
    from src.web.adapters.base import load_selectors

    image = load_selectors(SITE).get("image", {})
    return list(image.get("models", {})), list(image.get("aspects", {})), int(image.get("max_count", 4))


class WebFlowImageProvider(Provider):
    key = "web_flow_image"
    name = "Google Flow web (image)"
    site = SITE

    def __init__(self, session=None, pacer=None,
                 adapter_factory: Callable[[Any], Any] | None = None):
        self._session = session
        if pacer is None:
            from src.web.pacing import Pacer

            pacer = Pacer(SITE)
        self.pacer = pacer
        if adapter_factory is None:
            from src.web.adapters.flow import FlowAdapter

            adapter_factory = FlowAdapter
        self.adapter_factory = adapter_factory

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
            ConfigField("timeout", "gen_timeout", "int", 240, minimum=30, maximum=900),
        ]

    # ---- run ---------------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        timeout = float(options.get("timeout", 240))
        session = self.session
        with session.site_lock(SITE):
            if self.pacer.cap_reached():
                raise ProviderError(
                    f"Daily cap for {SITE_TITLE} reached ({self.pacer.cap} prompts). "
                    "Raise it in Settings → Web Sessions or try tomorrow.", stop_queue=True)
            if not self.pacer.wait_turn(ctx.should_stop):
                raise StopRequested()
            ctx.progress(0.05)
            try:
                files = session.run(SITE, lambda page: self._job(page, job, options, ctx, timeout),
                                    timeout=timeout + 180)
            except SiteBlocked as exc:
                session.bring_to_front(SITE)
                raise ProviderError(BLOCK_MESSAGES[exc.kind].format(site=SITE_TITLE),
                                    stop_queue=True) from None
            except UiChanged as exc:
                session.bring_to_front(SITE)
                raise ProviderError(f"{SITE_TITLE} UI not recognised ({exc}). Run Diagnose in "
                                    "Settings → Web Sessions and update selectors/flow.json.",
                                    stop_queue=True) from None
            except GenerationRefused as exc:
                raise ProviderError(f"{SITE_TITLE} refused the prompt: {exc}") from None
            except concurrent.futures.TimeoutError:
                raise ProviderError(f"{SITE_TITLE} did not finish in time", retryable=True) from None
            except (StopRequested, ProviderError):
                raise
            except Exception as exc:  # noqa: BLE001 - Playwright / browser errors
                from src.web.session import BrowserError

                if isinstance(exc, BrowserError):
                    raise ProviderError(str(exc), stop_queue=True) from None
                if "Timeout" in type(exc).__name__:
                    raise ProviderError(f"{SITE_TITLE} timed out: {str(exc).splitlines()[0]}",
                                        retryable=True) from None
                raise ProviderError(f"Browser error: {type(exc).__name__}: "
                                    f"{str(exc).splitlines()[0] if str(exc) else ''}",
                                    retryable=True) from None
            finally:
                self.pacer.mark_done()
        return files

    def _job(self, page, job: Job, options: dict[str, Any], ctx: RunContext,
             timeout: float) -> list[OutputFile]:
        """Runs on the site's browser thread."""
        adapter = self.adapter_factory(page)
        adapter.prepare()
        kind = adapter.detect_block()
        if kind:
            raise SiteBlocked(kind)
        if not adapter.is_logged_in():
            raise SiteBlocked("login")
        if ctx.should_stop():
            raise StopRequested()
        _, _, max_count = _flow_options()
        opts = dict(options)
        opts["count"] = max(1, min(int(options.get("count", 1)), max_count))
        adapter.submit(job.prompt, list(job.refs), opts)
        used = self.pacer.record_use()
        log.info("%s: job %d submitted (%d today)", SITE_TITLE, job.index, used)
        ctx.progress(0.15)
        adapter.wait_done(timeout, ctx.should_stop, lambda p: ctx.progress(0.15 + 0.75 * p))
        files = [OutputFile(data, ext) for data, ext in adapter.collect()]
        if not files:
            raise ProviderError(f"{SITE_TITLE} finished but no image could be downloaded",
                                retryable=True)
        return files
