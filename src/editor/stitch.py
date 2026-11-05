"""Join a run's clips, voice, music and effects into one video. No Qt: the CLI calls this.

A StitchSpec becomes an editor Project, so ``build_export`` and ``run_export`` do the work.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.editor.ffmpeg import ExportError, find_ffmpeg, missing_sources, probe, run_export, build_export
from src.editor.model import Clip, MIN_CLIP, Project, Track, media_kind

FALLBACK_FFMPEG = Path(r"D:\Apps\ffmpeg\ffmpeg-9.0.2-essentials_build\bin")
INSTALL_STEP = ("FFmpeg not found. Install it from https://ffmpeg.org/download.html, then set the ffmpegPath "
                "setting or the FFMPEG_PATH environment variable, or put it on PATH.")


class FfmpegNotFound(ExportError):
    pass


@dataclass
class StitchSpec:
    clips: list[dict]
    output: str
    voice: list[dict] = field(default_factory=list)
    bgm: dict | None = None
    sfx: list[dict] = field(default_factory=list)
    transition: dict | None = None
    size: tuple[int, int] = (1920, 1080)
    fps: int = 30
    loudness: float = -14

    @classmethod
    def from_dict(cls, data: dict) -> "StitchSpec":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if isinstance(known.get("size"), str):
            known["size"] = tuple(int(n) for n in known["size"].lower().split("x"))
        return cls(**known)


def resolve_ffmpeg(configured: str | None = None) -> str:
    """The setting, then FFMPEG_PATH, then PATH, then the known folder."""
    exe = find_ffmpeg(configured or os.environ.get("FFMPEG_PATH")) or find_ffmpeg(str(FALLBACK_FFMPEG))
    if not exe:
        raise FfmpegNotFound(INSTALL_STEP)
    return exe


def _clip_track(spec: StitchSpec, exe: str) -> Track:
    overlap = float((spec.transition or {}).get("duration", 0)) if (spec.transition or {}).get("type") == "fade" else 0.0
    track = Track("video", "Clips")
    at = 0.0
    for i, item in enumerate(spec.clips):
        path, hold = item["path"], float(item.get("hold", 0))
        if media_kind(path) == "image":
            clip = Clip("image", path, start=at, duration=max(MIN_CLIP, hold or 3.0))
        else:
            info = probe(exe, path)
            first = float(item.get("trim_start", 0))
            last = float(item.get("trim_end") or info.duration)
            clip = Clip("video", path, start=at, in_point=first, duration=max(MIN_CLIP, last - first) + hold,
                        source_duration=info.duration, has_audio=info.has_audio, hold=hold)
        if i and overlap:
            clip.fade_in = overlap
        track.clips.append(clip)
        at = clip.end - overlap
    return track


def to_project(spec: StitchSpec, exe: str) -> Project:
    width, height = spec.size
    project = Project(width=width, height=height, fps=spec.fps, loudness=spec.loudness)
    if not spec.clips:
        raise ExportError("A stitch needs at least one clip.")
    gone = [p for p in (c["path"] for c in spec.clips) if not Path(p).is_file()]
    if gone:
        raise ExportError("Missing input files:\n" + "\n".join(gone))  # probing them would hide which
    clips = _clip_track(spec, exe)
    total = clips.end
    project.tracks.append(clips)

    def sound(item: dict, length: float | None = None) -> Clip:
        start = float(item.get("start", 0))
        known = length if length is not None else probe(exe, item["path"]).duration if Path(item["path"]).is_file() else 0.0
        return Clip("audio", item["path"], start=start, duration=max(MIN_CLIP, known), volume=float(item.get("volume", 1)))

    if spec.voice:
        project.tracks.append(Track("audio", "Voice", [sound(v) for v in spec.voice], role="voice"))
    if spec.sfx:
        project.tracks.append(Track("audio", "Effects", [sound(s) for s in spec.sfx]))
    if spec.bgm:
        bed = sound(spec.bgm, total)
        bed.loop, bed.fade_out = True, float(spec.bgm.get("fade_out", 0))
        project.tracks.append(Track("audio", "Music", [bed], role="ducked" if spec.bgm.get("duck", True) else ""))
    return project


def stitch(spec: StitchSpec, on_progress: Callable[[float], None] = lambda f: None,
           should_stop: Callable[[], bool] = lambda: False) -> Path:
    exe = resolve_ffmpeg()
    output = Path(spec.output)
    project = to_project(spec, exe)
    gone = missing_sources(project)
    if gone:
        raise ExportError("Missing input files:\n" + "\n".join(gone))
    inputs = {Path(c.path).resolve() for t in project.tracks for c in t.clips}
    if output.resolve() in inputs:
        raise ExportError(f"The output would overwrite an input: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stitch-") as workdir:
        try:
            return run_export(exe, build_export(project, output), workdir, on_progress, should_stop)
        except ExportError:
            output.unlink(missing_ok=True)  # a half-written file must never pass for the result
            raise
