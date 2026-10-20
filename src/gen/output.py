"""Where generated files go and what they are called."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.gen.models import Job, OutputFile

SUBDIR_MODES = ("none", "date", "batch")


def default_save_dir(page_key: str) -> Path:
    from src.config import app_data_dir

    return app_data_dir() / "outputs" / page_key


def output_dir(base: Path | str, subdir_mode: str = "none", batch_stamp: str = "",
               now: datetime | None = None) -> Path:
    base = Path(base)
    if subdir_mode == "date":
        return base / (now or datetime.now()).strftime("%Y-%m-%d")
    if subdir_mode == "batch":
        return base / (batch_stamp or (now or datetime.now()).strftime("%Y%m%d-%H%M%S"))
    return base


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "prompt"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def save_outputs(job: Job, files: list[OutputFile], folder: Path | str) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for n, f in enumerate(files, 1):
        name = f"{job.index:03d}_{slugify(job.prompt)}_{n}.{f.ext.lstrip('.')}"
        path = unique_path(folder / name)
        path.write_bytes(f.data)
        saved.append(path)
    return saved
