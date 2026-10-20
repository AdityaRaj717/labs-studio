"""Offline provider for tests and the demo page. Makes no network calls.

Prompts containing ``[fail]`` always fail; ``[flaky]`` fails on the first
attempt with a retryable error.
"""

from __future__ import annotations

import hashlib
import io
import time
from typing import Any

from PIL import Image, ImageDraw

from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Provider, ProviderError, RunContext, StopRequested

ASPECTS = {"1:1": (256, 256), "16:9": (320, 180), "9:16": (180, 320), "4:3": (288, 216)}


class FakeProvider(Provider):
    key = "fake"
    name = "Demo provider (offline)"

    def __init__(self, step_seconds: float = 0.25, steps: int = 8):
        self.step_seconds = step_seconds
        self.steps = steps

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField("model", "gen_model", "choice", "fake-v1", ["fake-v1", "fake-v2"]),
            ConfigField("aspect", "gen_aspect", "choice", "1:1", list(ASPECTS)),
        ]

    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        for step in range(1, self.steps + 1):
            if ctx.should_stop():
                raise StopRequested()
            if self.step_seconds:
                time.sleep(self.step_seconds)
            ctx.progress(step / self.steps)
            if step == self.steps // 2:
                if "[fail]" in job.prompt:
                    raise ProviderError("Fake failure requested by prompt")
                if "[flaky]" in job.prompt and job.attempts <= 1:
                    raise ProviderError("Fake transient error", retryable=True)
        count = max(1, int(options.get("count", 1)))
        size = ASPECTS.get(options.get("aspect", "1:1"), ASPECTS["1:1"])
        return [OutputFile(render_png(f"{job.prompt} #{n}", size)) for n in range(1, count + 1)]


def render_png(text: str, size: tuple[int, int]) -> bytes:
    digest = hashlib.md5(text.encode("utf-8")).digest()
    img = Image.new("RGB", size, (digest[0], digest[1], digest[2]))
    ImageDraw.Draw(img).multiline_text((8, 8), _wrap(text, 28), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _wrap(text: str, width: int) -> str:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    return "\n".join(lines[:8])
