"""What the app shows (Phase 14b).

Today only the Google Flow web path works end to end (signed-in Chrome + the
google-flow MCP). Everything else (API-key providers, placeholder pages, local
video tools, the workflow editor) is hidden, not deleted, so the app shows what
the backend can do. One switch brings it all back:

- setting ``features.flow_only`` (default ``True``) in settings.json, or
- environment ``LABS_STUDIO_FEATURES=all`` (or ``flow``), which wins over the setting.

``HIDDEN`` lists each hidden page, provider and control with the reason;
``docs/phase-14b-handoff.md`` has the same list.
"""

from __future__ import annotations

import os

ENV = "LABS_STUDIO_FEATURES"

# Sidebar pages hidden in Flow-only mode -> why.
HIDDEN_PAGES: dict[str, str] = {
    "flow_video": "Gemini API video (Veo/Omni): needs an API key; Flow web video is not wired into the app yet",
    "grok": "xAI API: needs an API key, not checked against Flow",
    "openai_image": "OpenAI API: needs an API key, not checked against Flow",
    "meta_vibes": "placeholder page, nothing behind it",
    "meta_muse": "placeholder page, nothing behind it",
    "google_vids": "placeholder page, nothing behind it",
    "google_pics": "placeholder page, nothing behind it",
    "workflow": "node editor runs Gemini API / demo nodes, no Flow node",
    "video_editor": "local ffmpeg editor, not part of the Flow path",
    "upscaler": "local Real-ESRGAN tool, needs a binary download, not part of the Flow path",
    "video_cut": "local ffmpeg tool, not part of the Flow path",
    "course": "placeholder page, nothing behind it",
    "demo": "offline fake provider for testing the webhook",
}

# Other things hidden in Flow-only mode -> why (they are checked by name in the UI code).
HIDDEN: dict[str, str] = {
    **{f"page:{k}": v for k, v in HIDDEN_PAGES.items()},
    "provider:gemini_image": "Gemini API image provider on the image page: needs an API key",
    "settings:api_keys": "API keys tab: only the hidden API providers use keys",
    "settings:tools": "Tools tab (ffmpeg, Real-ESRGAN): only the hidden local tools use them",
    "characters:voice": "character voice + preview: Gemini TTS needs an API key",
    "webhook:demo": "webhook 'Open demo page' button: the demo page is hidden",
}


def flow_only() -> bool:
    env = os.environ.get(ENV, "").strip().lower()
    if env in ("all", "full", "0", "false"):
        return False
    if env in ("flow", "1", "true"):
        return True
    from src import config

    return bool(config.get("features.flow_only", True))


def shown(key: str) -> bool:
    """False when ``key`` (``page:<key>``, ``provider:<key>``, ``settings:<tab>``…) is hidden."""
    return not (flow_only() and key in HIDDEN)


def page_shown(page_key: str) -> bool:
    return shown(f"page:{page_key}")


def visible_pages(keys) -> tuple[str, ...]:
    return tuple(k for k in keys if page_shown(k))
