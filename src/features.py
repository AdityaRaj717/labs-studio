"""What the app shows (Phase 14b).

Only the Google Flow web path works end to end. One switch widens what the Characters page says:

- setting ``features.flow_only`` (default ``True``) in settings.json, or
- environment ``LABS_STUDIO_FEATURES=all`` (or ``flow``), which wins over the setting.
"""

from __future__ import annotations

import os

ENV = "LABS_STUDIO_FEATURES"

# Hidden in Flow-only mode -> why (checked by name in the UI code).
HIDDEN: dict[str, str] = {}


def flow_only() -> bool:
    env = os.environ.get(ENV, "").strip().lower()
    if env in ("all", "full", "0", "false"):
        return False
    if env in ("flow", "1", "true"):
        return True
    from src import config

    return bool(config.get("features.flow_only", True))


def shown(key: str) -> bool:
    """False when ``key`` (``page:<key>``, ``settings:<tab>``) is hidden."""
    return not (flow_only() and key in HIDDEN)


def page_shown(page_key: str) -> bool:
    return shown(f"page:{page_key}")


def visible_pages(keys) -> tuple[str, ...]:
    return tuple(k for k in keys if page_shown(k))
