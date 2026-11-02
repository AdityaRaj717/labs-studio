"""Editor project model: tracks, clips, subtitle cues and style. No Qt, so it unit-tests
and the ffmpeg export is built straight from it.

Times are seconds (float) on the timeline. Track order is bottom → top: the first
video track is the base layer, later video/overlay tracks are drawn over it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROJECT_EXT = ".lsproj"
PROJECT_VERSION = 1

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}

TRACK_KINDS = ("video", "overlay", "audio")
MIN_CLIP = 0.1  # shortest clip a trim or split may leave, in seconds


def media_kind(path: str | Path) -> str | None:
    """'image' / 'video' / 'audio' from the extension, None when unknown."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def _from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Clip:
    """One item on a track. ``kind`` is image / video / audio / text."""

    kind: str
    path: str = ""
    start: float = 0.0          # timeline position
    duration: float = 3.0       # length on the timeline
    in_point: float = 0.0       # offset into the source (video/audio)
    source_duration: float = 0.0  # 0 = unknown / unbounded (images, text)
    has_audio: bool = False     # video clips: source has an audio stream
    volume: float = 1.0
    loop: bool = False          # audio: loop the source to fill the clip
    fade_in: float = 0.0
    fade_out: float = 0.0
    hold: float = 0.0           # video: seconds of its last frame, included in duration
    # overlay placement (overlay tracks, text clips); x/y are 0..1 of the free space
    x: float = 0.5
    y: float = 0.5
    scale: float = 1.0          # width as a fraction of the frame width (overlays)
    opacity: float = 1.0
    # text clips
    text: str = ""
    font_size: int = 48
    color: str = "#ffffff"

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def name(self) -> str:
        if self.kind == "text":
            return self.text.splitlines()[0] if self.text else "Text"
        return Path(self.path).name

    def max_duration(self) -> float | None:
        """Longest the clip can be without running past its source (None = no limit)."""
        if self.kind in ("image", "text") or self.loop or self.source_duration <= 0:
            return None
        return max(MIN_CLIP, self.source_duration - self.in_point)


@dataclass
class Track:
    kind: str = "video"
    name: str = ""
    clips: list[Clip] = field(default_factory=list)
    muted: bool = False
    hidden: bool = False
    volume: float = 1.0
    role: str = ""              # audio: "voice" pushes "ducked" tracks down while it speaks

    def sorted_clips(self) -> list[Clip]:
        return sorted(self.clips, key=lambda c: c.start)

    @property
    def end(self) -> float:
        return max((c.end for c in self.clips), default=0.0)


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class SubtitleStyle:
    font: str = "Arial"
    size: int = 54
    color: str = "#ffffff"
    outline_color: str = "#000000"
    outline: float = 3.0
    shadow: float = 1.0
    bold: bool = True
    italic: bool = False
    position: str = "bottom"    # bottom / middle / top
    margin_v: int = 60
    box: bool = False           # opaque box behind the text
    box_color: str = "#000000"
    box_opacity: float = 0.6


@dataclass
class Project:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    background: str = "#000000"
    tracks: list[Track] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    style: SubtitleStyle = field(default_factory=SubtitleStyle)
    burn_subtitles: bool = True
    loudness: float | None = None  # target LUFS of the final mix

    @classmethod
    def new(cls, **kw) -> "Project":
        p = cls(**kw)
        p.tracks = [Track("video", "Video 1"), Track("overlay", "Overlay 1"), Track("audio", "Audio 1")]
        return p

    # ---- queries -----------------------------------------------------
    @property
    def duration(self) -> float:
        ends = [t.end for t in self.tracks if t.kind != "audio"]
        ends.append(max((c.end for c in self.cues), default=0.0))
        visual = max(ends, default=0.0)
        if visual > 0:
            return visual
        # audio-only project: use the audio length
        return max((t.end for t in self.tracks), default=0.0)

    def tracks_of(self, kind: str) -> list[Track]:
        return [t for t in self.tracks if t.kind == kind]

    def first_track(self, kind: str) -> Track:
        found = self.tracks_of(kind)
        if found:
            return found[0]
        return self.add_track(kind)

    def find(self, clip: Clip) -> Track | None:
        for t in self.tracks:
            if any(c is clip for c in t.clips):
                return t
        return None

    def cues_at(self, t: float) -> list[Cue]:
        return [c for c in self.cues if c.start <= t < c.end]

    # ---- edits -------------------------------------------------------
    def add_track(self, kind: str, name: str = "") -> Track:
        if kind not in TRACK_KINDS:
            raise ValueError(f"unknown track kind {kind!r}")
        n = len(self.tracks_of(kind)) + 1
        track = Track(kind, name or f"{kind.capitalize()} {n}")
        # keep audio tracks at the end, visual tracks in stacking order before them
        if kind == "audio":
            self.tracks.append(track)
        else:
            idx = max((i + 1 for i, t in enumerate(self.tracks) if t.kind != "audio"), default=0)
            self.tracks.insert(idx, track)
        return track

    def remove_track(self, track: Track) -> None:
        self.tracks = [t for t in self.tracks if t is not track]

    def append_clip(self, track: Track, clip: Clip, overlap: float = 0.0) -> Clip:
        """Put ``clip`` after the last clip on ``track`` (overlapping by ``overlap`` s)."""
        clip.start = max(0.0, track.end - overlap) if track.clips else 0.0
        track.clips.append(clip)
        return clip

    def remove_clip(self, clip: Clip) -> None:
        track = self.find(clip)
        if track is not None:
            track.clips = [c for c in track.clips if c is not clip]

    @staticmethod
    def move_clip(clip: Clip, start: float) -> None:
        clip.start = max(0.0, round(start, 3))

    @staticmethod
    def trim_clip(clip: Clip, start: float | None = None, end: float | None = None) -> None:
        """Move the left edge (keeps the right edge, shifts ``in_point``) and/or the right edge."""
        if start is not None:
            start = max(0.0, min(start, clip.end - MIN_CLIP))
            delta = start - clip.start
            if clip.kind in ("video", "audio") and not clip.loop:
                # can't pull the left edge before the start of the source
                delta = max(delta, -clip.in_point)
                clip.in_point = round(clip.in_point + delta, 3)
            clip.start = round(clip.start + delta, 3)
            clip.duration = round(clip.duration - delta, 3)
        if end is not None:
            dur = max(MIN_CLIP, end - clip.start)
            limit = clip.max_duration()
            if limit is not None:
                dur = min(dur, limit)
            clip.duration = round(dur, 3)

    def split_clip(self, clip: Clip, at: float) -> Clip | None:
        """Cut ``clip`` at timeline time ``at``. Returns the new right half, or None."""
        if not (clip.start + MIN_CLIP <= at <= clip.end - MIN_CLIP):
            return None
        track = self.find(clip)
        if track is None:
            return None
        right = copy.deepcopy(clip)
        left_dur = round(at - clip.start, 3)
        right.start = round(at, 3)
        right.duration = round(clip.duration - left_dur, 3)
        if clip.kind in ("video", "audio"):
            right.in_point = round(clip.in_point + left_dur, 3)
        clip.duration = left_dur
        # the cut edge gets no fade
        clip.fade_out = 0.0
        right.fade_in = 0.0
        track.clips.insert(track.clips.index(clip) + 1, right)
        return right

    def sort_cues(self) -> None:
        self.cues.sort(key=lambda c: (c.start, c.end))

    # ---- persistence -------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["version"] = PROJECT_VERSION
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        p = _from_dict(cls, {k: v for k, v in data.items() if k not in ("tracks", "cues", "style")})
        p.tracks = []
        for td in data.get("tracks", []):
            t = _from_dict(Track, {k: v for k, v in td.items() if k != "clips"})
            t.clips = [_from_dict(Clip, cd) for cd in td.get("clips", [])]
            p.tracks.append(t)
        p.cues = [_from_dict(Cue, cd) for cd in data.get("cues", [])]
        p.style = _from_dict(SubtitleStyle, data.get("style", {}))
        return p

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
