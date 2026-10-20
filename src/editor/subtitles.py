"""SRT / ASS read and write.

Export always burns an ASS file: the subtitle cues use the project's ``SubtitleStyle``
and text clips from overlay tracks become positioned events with their own size/colour,
so one libass pass draws both (no drawtext/fontconfig setup needed on Windows).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.editor.model import Clip, Cue, Project, SubtitleStyle

_SRT_TIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?")


# ---- time helpers ----------------------------------------------------------
def parse_srt_time(text: str) -> float:
    m = _SRT_TIME.fullmatch(text.strip())
    if not m:
        raise ValueError(f"bad SRT time {text!r}")
    h, mi, s, ms = m.groups()
    frac = int((ms or "0").ljust(3, "0"))
    return int(h) * 3600 + int(mi) * 60 + int(s) + frac / 1000


def format_srt_time(t: float) -> str:
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_ass_time(text: str) -> float:
    h, m, s = text.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def format_ass_time(t: float) -> str:
    cs = max(0, round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ---- SRT -------------------------------------------------------------------
def parse_srt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n")]
        # the index line is optional in the wild; find the timing line
        for i, ln in enumerate(lines):
            if "-->" in ln:
                a, b = ln.split("-->", 1)
                try:
                    start, end = parse_srt_time(a), parse_srt_time(b.split()[0])
                except (ValueError, IndexError):
                    break
                body = "\n".join(lines[i + 1:]).strip()
                body = re.sub(r"</?[biu]>|</?font[^>]*>", "", body)
                if body and end > start:
                    cues.append(Cue(start, end, body))
                break
    cues.sort(key=lambda c: c.start)
    return cues


def write_srt(cues: list[Cue]) -> str:
    out = []
    for i, c in enumerate(sorted(cues, key=lambda c: c.start), 1):
        out.append(f"{i}\n{format_srt_time(c.start)} --> {format_srt_time(c.end)}\n{c.text}\n")
    return "\n".join(out)


# ---- ASS -------------------------------------------------------------------
def _ass_text_in(text: str) -> str:
    text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    return re.sub(r"\{[^}]*\}", "", text).strip()


def parse_ass(text: str) -> list[Cue]:
    """Dialogue events of an .ass/.ssa file (override tags stripped, styles ignored)."""
    cues: list[Cue] = []
    fmt: list[str] | None = None
    section = ""
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.lower()
            continue
        if section != "[events]":
            continue
        if line.lower().startswith("format:"):
            fmt = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
        elif line.lower().startswith("dialogue:") and fmt:
            parts = line.split(":", 1)[1].split(",", len(fmt) - 1)
            row = dict(zip(fmt, (p.strip() if k != "text" else p for k, p in zip(fmt, parts))))
            try:
                start, end = parse_ass_time(row["start"]), parse_ass_time(row["end"])
            except (KeyError, ValueError):
                continue
            body = _ass_text_in(row.get("text", ""))
            if body and end > start:
                cues.append(Cue(start, end, body))
    cues.sort(key=lambda c: c.start)
    return cues


def load_subtitles(path: str | Path) -> list[Cue]:
    path = Path(path)
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() in (".ass", ".ssa"):
        return parse_ass(text)
    return parse_srt(text)


def ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """'#rrggbb' → '&HAABBGGRR' (ASS alpha 00 = opaque)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "ffffff"
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = round((1 - max(0.0, min(1.0, opacity))) * 255)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


_ALIGN = {"bottom": 2, "middle": 5, "top": 8}


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _style_line(name: str, s: SubtitleStyle, size: int | None = None, color: str | None = None,
                align: int | None = None) -> str:
    back = ass_color(s.box_color, s.box_opacity) if s.box else ass_color("#000000", 0.5)
    border_style = 3 if s.box else 1
    return (
        f"Style: {name},{s.font},{size or s.size},{ass_color(color or s.color)},&H000000FF,"
        f"{ass_color(s.outline_color)},{back},{-1 if s.bold else 0},{-1 if s.italic else 0},0,0,"
        f"100,100,0,0,{border_style},{s.outline:g},{s.shadow:g},"
        f"{align or _ALIGN.get(s.position, 2)},40,40,{s.margin_v},1"
    )


def text_clip_pos(clip: Clip, width: int, height: int) -> tuple[int, int]:
    """Anchor point (centre) of a text clip in output pixels."""
    return round(clip.x * width), round(clip.y * height)


def build_ass(project: Project, include_cues: bool = True, text_clips: list[Clip] | None = None) -> str:
    s = project.style
    lines = [
        "[Script Info]",
        "; Written by Labs Studio",
        "ScriptType: v4.00+",
        f"PlayResX: {project.width}",
        f"PlayResY: {project.height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Default", s),
        _style_line("Text", s, align=5),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if include_cues:
        for c in sorted(project.cues, key=lambda c: c.start):
            lines.append(f"Dialogue: 1,{format_ass_time(c.start)},{format_ass_time(c.end)},Default,,0,0,0,,"
                         f"{_escape_ass(c.text)}")
    for clip in text_clips or []:
        x, y = text_clip_pos(clip, project.width, project.height)
        tags = f"\\pos({x},{y})\\fs{clip.font_size}\\1c{_bgr(clip.color)}"
        if clip.opacity < 1:
            tags += f"\\alpha&H{round((1 - clip.opacity) * 255):02X}&"
        if clip.fade_in or clip.fade_out:
            tags += f"\\fad({round(clip.fade_in * 1000)},{round(clip.fade_out * 1000)})"
        lines.append(f"Dialogue: 2,{format_ass_time(clip.start)},{format_ass_time(clip.end)},Text,,0,0,0,,"
                     f"{{{tags}}}{_escape_ass(clip.text)}")
    return "\n".join(lines) + "\n"


def _bgr(hex_color: str) -> str:
    """'#rrggbb' → '&HBBGGRR&' for inline \\1c tags."""
    return "&H" + ass_color(hex_color)[4:] + "&"
