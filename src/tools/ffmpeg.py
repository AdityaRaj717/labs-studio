"""ffmpeg/ffprobe command building for the slicer and frame extractor.

Everything here is pure (no processes): ``probe`` takes a ``run`` callable so
tests feed it canned ffprobe JSON.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.gen.provider import ProviderError

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".mpg", ".mpeg"}

SLICE_MODES = ("duration", "parts", "ranges")
ENCODE_MODES = ("copy", "reencode")
FRAME_MODES = ("interval", "count", "all", "first", "last", "times")
FRAME_FORMATS = ("png", "jpg")


@dataclass
class MediaInfo:
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False


# ---- time strings ---------------------------------------------------------
def parse_time(text: str) -> float:
    """``"90"``, ``"1:30"``, ``"0:01:30.5"`` → seconds."""
    text = text.strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time: {text}")
    total = 0.0
    for part in parts:
        if not re.fullmatch(r"\d+(\.\d+)?", part.strip()):
            raise ValueError(f"bad time: {text}")
        total = total * 60 + float(part)
    return total


def format_time(seconds: float) -> str:
    """Seconds → ``H:MM:SS.mmm`` (what ffmpeg accepts for -ss/-t)."""
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:06.3f}"


def label_time(seconds: float) -> str:
    """Filename-safe stamp, e.g. ``0m05.250s``."""
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}m{s:06.3f}s"


def parse_ranges(text: str, duration: float) -> list[tuple[float, float]]:
    """``"0:05-0:12, 1:00-"`` → [(5, 12), (60, duration)]. Ends past the clip are clamped."""
    ranges = []
    for chunk in re.split(r"[,;\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" not in chunk:
            raise ValueError(f"range needs start-end: {chunk}")
        a, b = chunk.split("-", 1)
        start = parse_time(a)
        end = parse_time(b) if b.strip() else duration
        if duration > 0:
            end = min(end, duration)
        if end <= start:
            raise ValueError(f"range ends before it starts: {chunk}")
        ranges.append((start, end))
    if not ranges:
        raise ValueError("no ranges given")
    return ranges


def parse_times(text: str, duration: float = 0.0) -> list[float]:
    times = [parse_time(t) for t in re.split(r"[,;\s]+", text) if t.strip()]
    if not times:
        raise ValueError("no timestamps given")
    if duration > 0:
        times = [min(t, max(0.0, duration - 0.05)) for t in times]
    return times


# ---- probe ----------------------------------------------------------------
def probe_cmd(ffprobe: Path, src: Path) -> list[str]:
    return [str(ffprobe), "-v", "error", "-print_format", "json", "-show_format",
            "-show_streams", str(src)]


def _rate(text: str) -> float:
    try:
        num, _, den = text.partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_probe(text: str) -> MediaInfo:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"ffprobe returned no readable info ({exc})") from exc
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProviderError("No video stream in this file.")
    duration = 0.0
    for raw in ((data.get("format") or {}).get("duration"), video.get("duration")):
        try:
            duration = float(raw)
            break
        except (TypeError, ValueError):
            continue
    return MediaInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def probe(ffprobe: Path, src: Path, run: Callable[[list[str]], str]) -> MediaInfo:
    """``run(cmd) -> stdout``; see ``tools.runner.capture``."""
    return parse_probe(run(probe_cmd(ffprobe, src)))


# ---- progress -------------------------------------------------------------
_OUT_TIME = re.compile(r"^out_time_(?:us|ms)=(\d+)")
_OUT_TIME_HMS = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def progress_seconds(line: str) -> float | None:
    """Seconds done from one ``-progress pipe:1`` line, else None."""
    m = _OUT_TIME.match(line)
    if m:
        return int(m.group(1)) / 1_000_000  # out_time_ms is microseconds too
    m = _OUT_TIME_HMS.match(line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


_BASE = ["-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]


# ---- slicer ---------------------------------------------------------------
@dataclass
class Segment:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def plan_segments(mode: str, duration: float, seconds: float = 10.0, parts: int = 2,
                  ranges: str = "", min_tail: float = 0.25) -> list[Segment]:
    if mode == "duration":
        if seconds <= 0:
            raise ValueError("segment length must be > 0")
        if duration <= 0:
            raise ValueError("unknown clip length")
        segs, t = [], 0.0
        while t < duration - 1e-6:
            end = min(t + seconds, duration)
            segs.append(Segment(t, end))
            t = end
        # Fold a sliver at the end into the previous piece.
        if len(segs) > 1 and segs[-1].length < min_tail:
            last = segs.pop()
            segs[-1].end = last.end
        return segs
    if mode == "parts":
        if parts < 1:
            raise ValueError("parts must be >= 1")
        if duration <= 0:
            raise ValueError("unknown clip length")
        step = duration / parts
        return [Segment(i * step, duration if i == parts - 1 else (i + 1) * step) for i in range(parts)]
    if mode == "ranges":
        return [Segment(a, b) for a, b in parse_ranges(ranges, duration)]
    raise ValueError(f"unknown slice mode: {mode}")


def slice_cmd(ffmpeg: Path, src: Path, seg: Segment, dst: Path, encode: str = "copy",
              crf: int = 18) -> list[str]:
    """One segment. ``copy`` is fast but starts on the nearest keyframe; ``reencode`` is exact."""
    cmd = [str(ffmpeg), *_BASE, "-ss", format_time(seg.start), "-i", str(src),
           "-t", format_time(seg.length), "-map", "0:v:0", "-map", "0:a?"]
    mp4_family = dst.suffix.lower() in (".mp4", ".mov", ".m4v")
    if encode == "copy":
        cmd += ["-c", "copy"]
        # MP4/MOV hide the keyframe pre-roll with an edit list; make_zero would expose it.
        if not mp4_family:
            cmd += ["-avoid_negative_ts", "make_zero"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    if mp4_family:
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    return cmd


def segment_name(stem: str, index: int, seg: Segment, ext: str) -> str:
    return f"{stem}_part{index:03d}_{label_time(seg.start)}{ext}"


def slice_ext(src: Path, encode: str) -> str:
    """Stream copy keeps the container; re-encode writes H.264/AAC into .mp4."""
    if encode == "copy":
        return src.suffix.lower() or ".mp4"
    return ".mp4"


# ---- frame extractor ------------------------------------------------------
def _quality_args(fmt: str, jpg_quality: int) -> list[str]:
    if fmt == "jpg":
        # Map 1..100 (higher = better) to ffmpeg's 31..2.
        q = round(31 - (max(1, min(100, jpg_quality)) - 1) * 29 / 99)
        return ["-q:v", str(q)]
    return []


def frames_sequence_cmd(ffmpeg: Path, src: Path, folder: Path, stem: str, mode: str,
                        interval: float = 1.0, fmt: str = "png", jpg_quality: int = 92) -> list[str]:
    """``interval`` (one frame every N s) and ``all`` write a numbered sequence."""
    cmd = [str(ffmpeg), *_BASE, "-i", str(src), "-map", "0:v:0"]
    if mode == "interval":
        if interval <= 0:
            raise ValueError("interval must be > 0")
        cmd += ["-vf", f"fps=1/{interval:g}"]
    elif mode == "all":
        cmd += ["-fps_mode", "passthrough"]
    else:
        raise ValueError(mode)
    cmd += _quality_args(fmt, jpg_quality)
    cmd.append(str(folder / f"{stem}_%06d.{fmt}"))
    return cmd


def frame_at_cmd(ffmpeg: Path, src: Path, t: float, dst: Path, fmt: str = "png",
                 jpg_quality: int = 92) -> list[str]:
    return [str(ffmpeg), *_BASE, "-ss", format_time(t), "-i", str(src), "-map", "0:v:0",
            "-frames:v", "1", *_quality_args(fmt, jpg_quality), "-update", "1", str(dst)]


def last_frame_cmd(ffmpeg: Path, src: Path, dst: Path, fmt: str = "png",
                   jpg_quality: int = 92) -> list[str]:
    # Decode the last ~3 s and keep overwriting one file: the last write is the last frame.
    return [str(ffmpeg), *_BASE, "-sseof", "-3", "-i", str(src), "-map", "0:v:0",
            *_quality_args(fmt, jpg_quality), "-update", "1", str(dst)]


def evenly_spaced(duration: float, count: int) -> list[float]:
    if count < 1:
        raise ValueError("count must be >= 1")
    if duration <= 0:
        raise ValueError("unknown clip length")
    return [duration * (i + 0.5) / count for i in range(count)]


def expected_frames(mode: str, info: MediaInfo, interval: float) -> int:
    """Rough frame count for progress text (0 = unknown)."""
    if mode == "interval" and interval > 0:
        return max(1, math.ceil(info.duration / interval))
    if mode == "all" and info.fps > 0:
        return max(1, round(info.duration * info.fps))
    return 0
