"""Offline demo nodes: try a graph without a key. No network calls.

The image node is the Phase 2 FakeProvider. The video node makes a short
animated GIF (from the start frame when one is wired in).
"""

from __future__ import annotations

import io
import time
from typing import Any

from PIL import Image, ImageDraw

from src.gen.fake_provider import ASPECTS, FakeProvider, render_png
from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, RunContext, StopRequested
from src.workflow.provider_node import provider_node
from src.workflow.registry import IMAGE, VIDEO, Port, register

CATEGORY = "wf_cat_demo"


class FakeVideoProvider(Provider):
    key = "fake_video"
    name = "Demo video (offline)"

    def __init__(self, step_seconds: float = 0.15, frames: int = 8):
        self.step_seconds = step_seconds
        self.frames = frames

    def config_fields(self) -> list[ConfigField]:
        return [ConfigField("aspect", "gen_aspect", "choice", "16:9", list(ASPECTS))]

    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        size = ASPECTS.get(options.get("aspect", "16:9"), ASPECTS["16:9"])
        if job.refs:
            base = Image.open(job.refs[0]).convert("RGB").resize(size)
        else:
            base = Image.open(io.BytesIO(render_png(job.prompt, size))).convert("RGB")
        frames = []
        for n in range(self.frames):
            if ctx.should_stop():
                raise StopRequested()
            if self.step_seconds:
                time.sleep(self.step_seconds)
            frame = base.copy()
            x = int((size[0] - 24) * n / max(1, self.frames - 1))
            ImageDraw.Draw(frame).rectangle([x, size[1] - 14, x + 24, size[1] - 4], fill=(255, 255, 255))
            frames.append(frame)
            ctx.progress((n + 1) / self.frames)
        count = max(1, int(options.get("count", 1)))
        buf = io.BytesIO()
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=120, loop=0)
        return [OutputFile(buf.getvalue(), "gif") for _ in range(count)]


def image_node(make_provider=FakeProvider):
    return provider_node("demo.image", "wf_node_demo_image", CATEGORY, make_provider, output=IMAGE)


def video_node(make_provider=FakeVideoProvider):
    return provider_node("demo.video", "wf_node_demo_video", CATEGORY, make_provider, output=VIDEO,
                         refs=Port("start", IMAGE, "wf_port_start", required=False))


register(image_node())
register(video_node())
