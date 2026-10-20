"""Auto-edit: turn a folder of images/clips (plus optional music) into a timeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.editor.model import Clip, Project, media_kind

Prober = Callable[[str], "object"]  # path → MediaInfo-like (duration, has_audio)


def natural_key(path: str | Path) -> list:
    name = Path(path).name.lower()
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


def scan_folder(folder: str | Path) -> list[str]:
    """Images and videos in ``folder`` (not recursive), natural sort order."""
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.is_file() and media_kind(p) in ("image", "video")]
    return [str(p) for p in sorted(files, key=natural_key)]


@dataclass
class SlideshowOptions:
    image_duration: float = 3.0
    transition: float = 0.5        # crossfade length between items (0 = hard cuts)
    max_clip: float = 0.0          # cap on video clip length (0 = use the whole clip)
    fade_edges: bool = True        # fade in from / out to the background at both ends
    music: str = ""
    music_volume: float = 0.8
    music_fade_out: float = 2.0
    keep_clip_audio: bool = True


def build_slideshow(paths: list[str], opts: SlideshowOptions | None = None,
                    probe: Prober | None = None, project: Project | None = None) -> Project:
    """Lay ``paths`` end to end on the first video track. Each item fades in over the one
    before it (an alpha crossfade), and music is looped under the whole thing."""
    opts = opts or SlideshowOptions()
    project = project or Project.new()
    track = project.first_track("video")
    track.clips.clear()
    overlap = max(0.0, opts.transition)
    for path in paths:
        kind = media_kind(path)
        if kind not in ("image", "video"):
            continue
        clip = Clip(kind, path, duration=opts.image_duration)
        if kind == "video":
            info = probe(path) if probe else None
            src = float(getattr(info, "duration", 0.0) or 0.0)
            clip.source_duration = src
            clip.has_audio = bool(getattr(info, "has_audio", False)) and opts.keep_clip_audio
            dur = src or opts.image_duration
            if opts.max_clip > 0:
                dur = min(dur, opts.max_clip)
            clip.duration = round(dur, 3)
        # a crossfade can't be longer than half of either neighbour
        fade = min(overlap, clip.duration / 2)
        if track.clips:
            fade = min(fade, track.clips[-1].duration / 2)
            clip.fade_in = round(fade, 3)
        project.append_clip(track, clip, overlap=fade if track.clips else 0.0)

    if track.clips and opts.fade_edges and overlap > 0:
        track.clips[0].fade_in = round(min(overlap, track.clips[0].duration / 2), 3)
        track.clips[-1].fade_out = round(min(overlap, track.clips[-1].duration / 2), 3)

    if opts.music:
        audio = project.first_track("audio")
        audio.clips = [c for c in audio.clips if c.path != opts.music]
        info = probe(opts.music) if probe else None
        src = float(getattr(info, "duration", 0.0) or 0.0)
        total = track.end
        music = Clip("audio", opts.music, start=0.0, duration=round(total, 3), source_duration=src,
                     volume=opts.music_volume, loop=bool(src and src < total),
                     fade_out=min(opts.music_fade_out, total / 2))
        audio.clips.insert(0, music)
    return project
