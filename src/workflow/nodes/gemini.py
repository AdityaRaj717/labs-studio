"""Gemini nodes over the Phase 3/4 providers (the user's own Gemini key)."""

from __future__ import annotations

from src.workflow.provider_node import provider_node
from src.workflow.registry import IMAGE, VIDEO, Port, register

CATEGORY = "wf_cat_gemini"


def _image_provider():
    from src.gen.gemini_image import GeminiImageProvider

    return GeminiImageProvider()


def _video_provider():
    from src.gen.gemini_video import GeminiVideoProvider

    return GeminiVideoProvider()


def image_node(make_provider=_image_provider):
    return provider_node("gemini.image", "wf_node_gemini_image", CATEGORY, make_provider,
                         output=IMAGE, refs=Port("refs", IMAGE, "wf_port_refs", required=False))


def video_node(make_provider=_video_provider):
    # One wired image = start frame, two = start + end (the provider's "auto" task).
    return provider_node("gemini.video", "wf_node_gemini_video", CATEGORY, make_provider,
                         output=VIDEO, refs=Port("start", IMAGE, "wf_port_start", required=False))


register(image_node())
register(video_node())
