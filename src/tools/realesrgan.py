"""Real-ESRGAN (ncnn-vulkan build) command building and progress parsing.

The user installs ``realesrgan-ncnn-vulkan`` (with its ``models`` folder)
themselves; the app only calls it.
"""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# model name -> scales it supports (the x4plus models are fixed at 4x).
MODELS: dict[str, tuple[int, ...]] = {
    "realesrgan-x4plus": (4,),
    "realesrgan-x4plus-anime": (4,),
    "realesr-animevideov3": (2, 3, 4),
}
OUTPUT_FORMATS = ("png", "jpg", "webp")

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def check_scale(model: str, scale: int) -> int:
    scales = MODELS.get(model)
    if scales is None:
        raise ValueError(f"unknown model: {model}")
    return scale if scale in scales else scales[-1]


def upscale_cmd(exe: Path, src: Path, dst: Path, model: str = "realesrgan-x4plus", scale: int = 4,
                fmt: str = "png", tile: int = 0, tta: bool = False, gpu: str = "auto") -> list[str]:
    scale = check_scale(model, scale)
    cmd = [str(exe), "-i", str(src), "-o", str(dst), "-n", model, "-s", str(scale), "-f", fmt]
    models_dir = exe.parent / "models"
    if models_dir.is_dir():
        cmd += ["-m", str(models_dir)]
    if tile > 0:
        cmd += ["-t", str(tile)]
    if gpu and gpu != "auto":
        cmd += ["-g", gpu]
    if tta:
        cmd.append("-x")
    return cmd


def progress_fraction(line: str) -> float | None:
    """``"45.83%"`` → 0.4583 (Real-ESRGAN prints one per tile)."""
    m = _PERCENT.search(line)
    if not m:
        return None
    return max(0.0, min(1.0, float(m.group(1)) / 100))


def output_name(src: Path, scale: int, fmt: str) -> str:
    return f"{src.stem}_x{scale}.{fmt}"
