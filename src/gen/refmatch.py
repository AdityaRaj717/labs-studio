"""Match reference images in a folder to prompts by filename keyword."""

from __future__ import annotations

import re
from pathlib import Path

from src.gen.models import Job

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def list_ref_images(folder: Path | str) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def normalise(stem: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-.]+", " ", stem)).strip().lower()


def matches(prompt: str, index: int, image: Path) -> bool:
    """A stem matches its whole-word phrase in the prompt, or a numeric stem the row index."""
    key = normalise(image.stem)
    if not key:
        return False
    if key.isdigit():
        return int(key) == index
    return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", prompt.lower()) is not None


def match_refs(jobs: list[Job], folder: Path | str) -> int:
    """Attach matching images to each job (keeps refs already there). Returns refs added."""
    images = list_ref_images(folder)
    added = 0
    for job in jobs:
        for image in images:
            if image not in job.refs and matches(job.prompt, job.index, image):
                job.refs.append(image)
                added += 1
    return added
