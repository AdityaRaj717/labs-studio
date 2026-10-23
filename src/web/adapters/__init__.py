"""Per-site checks for the web-session providers."""

from __future__ import annotations

from src.web.adapters.base import page_status

SITE_TITLES = {"flow": "Google Flow"}

__all__ = ["SITE_TITLES", "page_status"]
