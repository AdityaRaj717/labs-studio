"""Find the external binaries the tools need.

Nothing is downloaded or bundled. A binary is taken from the setting
``tools.<name>_path`` (a file or the folder holding it), and
otherwise from PATH. ffprobe also looks next to a configured ffmpeg.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# tool id -> executable base names to look for (first match wins)
EXE_NAMES: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("ffmpeg",),
    "ffprobe": ("ffprobe",),
}

TOOL_IDS = tuple(EXE_NAMES)


def setting_key(tool: str) -> str:
    return f"tools.{tool}_path"


def _store(store):
    if store is not None:
        return store
    from src import config

    return config.settings()


def _exe_files(folder: Path, tool: str) -> list[Path]:
    suffix = ".exe" if sys.platform == "win32" else ""
    return [folder / f"{name}{suffix}" for name in EXE_NAMES[tool]]


def _resolve_configured(raw: str, tool: str) -> Path | None:
    path = Path(raw).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        for candidate in _exe_files(path, tool):
            if candidate.is_file():
                return candidate
    return None


def find_binary(tool: str, store=None, which=shutil.which) -> Path | None:
    """Return the binary for ``tool`` (``ffmpeg``/``ffprobe``) or None."""
    if tool not in EXE_NAMES:
        raise KeyError(tool)
    store = _store(store)
    raw = (store.get(setting_key(tool), "") or "").strip()
    if raw:
        found = _resolve_configured(raw, tool)
        if found:
            return found
    if tool == "ffprobe":
        ffmpeg_raw = (store.get(setting_key("ffmpeg"), "") or "").strip()
        ffmpeg = _resolve_configured(ffmpeg_raw, "ffmpeg") if ffmpeg_raw else None
        if ffmpeg:
            for candidate in _exe_files(ffmpeg.parent, "ffprobe"):
                if candidate.is_file():
                    return candidate
    for name in EXE_NAMES[tool]:
        hit = which(name)
        if hit:
            return Path(hit)
    return None


def missing(tools: tuple[str, ...] | list[str], store=None, which=shutil.which) -> list[str]:
    """Tool ids from ``tools`` that can't be found."""
    return [t for t in tools if find_binary(t, store, which) is None]
