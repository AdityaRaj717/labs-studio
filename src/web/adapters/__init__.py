"""Site adapters for the web-session providers."""

from __future__ import annotations

SITE_TITLES = {"flow": "Google Flow"}


def adapter_class(site: str):
    if site == "flow":
        from src.web.adapters.flow import FlowAdapter

        return FlowAdapter
    raise KeyError(site)


def page_status(page, site: str) -> str:
    """``ok``, or the block kind (``login`` / ``captcha`` / ``quota``). Runs on the site thread."""
    adapter = adapter_class(site)(page)
    return adapter.detect_block() or ("ok" if adapter.is_logged_in() else "login")
