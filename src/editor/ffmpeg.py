"""ffmpeg for the editor: find the binary, probe media, build the export command from a
``Project``, and run it with progress and cancel.

ffmpeg is external: found at the path saved in settings (``tools.ffmpeg_path``) or on
PATH, never downloaded or bundled. ``subprocess`` entry points are injectable so tests
mock them. (Phase 7 may carry its own helper; reconcile the two at merge time.)
"""

from __future__ import annotations

import logging
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.editor.model import Clip, Project, Track
from src.editor.subtitles import build_ass, write_srt

log = logging.getLogger(__name__)

SETTINGS_KEY = "tools.ffmpeg_path"
ASS_NAME = "subs.ass"
GRAPH_NAME = "graph.txt"
GRAPH_INLINE_LIMIT = 6000  # longer graphs go through `-/filter_complex <file>` (ffmpeg 7+)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class ExportError(RuntimeError):
    pass


class ExportCancelled(ExportError):
    pass


# ---- locating ---------------------------------------------------------------
def find_ffmpeg(configured: str | None = None, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """The configured binary (file, or folder holding ffmpeg[.exe]) if it exists, else PATH."""
    if configured:
        p = Path(configured.strip().strip('"'))
        if p.is_dir():
            for name in ("ffmpeg.exe", "ffmpeg"):
                if (p / name).is_file():
                    return str(p / name)
            for name in ("bin/ffmpeg.exe", "bin/ffmpeg"):
                if (p / name).is_file():
                    return str(p / name)
        elif p.is_file():
            return str(p)
    return which("ffmpeg")


def ffmpeg_version(exe: str, run=subprocess.run) -> str | None:
    try:
        r = run([exe, "-hide_banner", "-version"], capture_output=True, text=True, timeout=15,
                creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"ffmpeg version (\S+)", r.stdout or "")
    return m.group(1) if m else None


# ---- probing ----------------------------------------------------------------
@dataclass
class MediaInfo:
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0


def last_frame(exe: str, video: str | Path, run=None, timeout: float = 60) -> Path:
    """The video's last frame as ``<stem>_last.png`` beside it, as the engine's ``last_frame`` makes it."""
    video = Path(video)
    out = video.with_name(f"{video.stem}_last.png")
    # Decode the last 3 s and keep overwriting one file: the last write is the last frame.
    (run or subprocess.run)([exe, "-y", "-v", "error", "-sseof", "-3", "-i", str(video), "-map", "0:v:0", "-update", "1", str(out)],
        check=True, capture_output=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out


def parse_probe(stderr: str) -> MediaInfo:
    info = MediaInfo()
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in stderr.splitlines():
        if "Stream #" not in line:
            continue
        if "Video:" in line and "attached pic" not in line:
            info.has_video = True
            dm = re.search(r",\s*(\d{2,5})x(\d{2,5})", line)
            if dm and not info.width:
                info.width, info.height = int(dm.group(1)), int(dm.group(2))
        elif "Audio:" in line:
            info.has_audio = True
    return info


def probe(exe: str, path: str | Path, run=subprocess.run) -> MediaInfo:
    """Duration and streams from `ffmpeg -i` (no ffprobe needed)."""
    try:
        r = run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("probe failed for %s: %s", path, exc)
        return MediaInfo()
    return parse_probe(r.stderr or "")


# ---- command building -------------------------------------------------------
@dataclass
class ExportSettings:
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "192k"
    write_srt: bool = False   # also save the cues next to the video as .srt


@dataclass
class ExportPlan:
    inputs: list[str]             # input args
    graph: str                    # filter_complex text
    maps: list[str]               # -map args
    output: list[str]             # codec/output args, ends with the output path
    duration: float
    ass_text: str | None = None   # written to ASS_NAME in the work dir
    srt_text: str | None = None
    sources: list[str] = field(default_factory=list)

    def args(self, graph_file: str | None = None) -> list[str]:
        """ffmpeg arguments (without the executable). With ``graph_file`` the graph is read
        from that file instead of being passed inline."""
        g = ["-/filter_complex", graph_file] if graph_file else ["-filter_complex", self.graph]
        return ["-hide_banner", "-y", *self.inputs, *g, *self.maps, *self.output]


def _f(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def _hex(color: str) -> str:
    h = color.lstrip("#")
    return "0x" + (h if len(h) == 6 else "000000")


def _enable(start: float, end: float) -> str:
    return f"enable='between(t,{_f(start)},{_f(end)})'"


def _visual_layers(project: Project) -> list[tuple[Track, Clip]]:
    layers = []
    for t in project.tracks:
        if t.kind == "audio" or t.hidden:
            continue
        for c in t.sorted_clips():
            if c.kind in ("image", "video") and c.duration > 0:
                layers.append((t, c))
    return layers


def _text_clips(project: Project) -> list[Clip]:
    return [c for t in project.tracks if t.kind != "audio" and not t.hidden
            for c in t.sorted_clips() if c.kind == "text" and c.text.strip()]


def _audio_sources(project: Project) -> list[tuple[Clip, float, int | None]]:
    """(clip, gain, visual-input-slot or None) for every clip that contributes audio."""
    out = []
    for t in project.tracks:
        if t.muted:
            continue
        for c in t.sorted_clips():
            if t.kind == "audio" and c.kind == "audio":
                out.append((c, c.volume * t.volume, None))
            elif t.kind != "audio" and not t.hidden and c.kind == "video" and c.has_audio:
                out.append((c, c.volume * t.volume, -1))
    return [x for x in out if x[1] > 0]


def _duck(project: Project, labels: list[str], keys: list[str], graph: list[str]) -> list[str]:
    """Press "ducked" tracks down with ``keys``, a second copy of the voice. Returns the labels to mix."""
    clips = {id(c) for t in project.tracks if t.role == "ducked" for c in t.clips}
    ducked = [label for label, (c, _, _) in zip(labels, _audio_sources(project)) if id(c) in clips]
    if not keys or not ducked:
        return labels

    def joined(group: list[str]) -> str:
        return f"{''.join(group)}amix=inputs={len(group)}:normalize=0:dropout_transition=0" if len(group) > 1 else f"{group[0]}anull"
    graph.append(f"{joined(keys)},apad=whole_dur={_f(project.duration)}[vkey]")  # the bed goes on after the voice
    graph.append(f"{joined(ducked)}[bed]")
    graph.append("[bed][vkey]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=300[bedout]")
    return [label for label in labels if label not in ducked] + ["[bedout]"]


def missing_sources(project: Project) -> list[str]:
    paths = {c.path for t in project.tracks for c in t.clips if c.kind != "text"}
    return sorted(p for p in paths if not Path(p).is_file())


def build_export(project: Project, out_path: str | Path, settings: ExportSettings | None = None) -> ExportPlan:
    """Turn the project into one ffmpeg run. Input 0 is a background colour source, every
    image/video clip and every audio clip is its own input, already cut with -ss/-t."""
    settings = settings or ExportSettings()
    total = round(project.duration, 3)
    if total <= 0:
        raise ExportError("The timeline is empty.")
    W, H, fps = project.width, project.height, project.fps

    inputs = ["-f", "lavfi", "-i", f"color=c={_hex(project.background)}:s={W}x{H}:r={fps}:d={_f(total)}"]
    graph: list[str] = []
    sources: list[str] = []
    n_inputs = 1
    video_slot: dict[int, int] = {}  # id(clip) → input index

    def add_input(args: list[str]) -> int:
        nonlocal n_inputs
        inputs.extend(args)
        n_inputs += 1
        return n_inputs - 1

    # -- picture
    prev = "0:v"
    for k, (track, c) in enumerate(_visual_layers(project)):
        dur = _f(c.duration)
        if c.kind == "image":
            idx = add_input(["-loop", "1", "-framerate", str(fps), "-t", dur, "-i", c.path])
        else:
            pre = ["-stream_loop", "-1"] if c.loop else []
            idx = add_input([*pre, "-ss", _f(c.in_point), "-t", _f(c.duration - c.hold), "-i", c.path])
            video_slot[id(c)] = idx
        sources.append(c.path)

        hold = [f"tpad=stop_mode=clone:stop_duration={_f(c.hold)}"] if c.hold > 0 else []
        chain = [*hold, f"fps={fps}", f"trim=duration={dur}", "setpts=PTS-STARTPTS"]
        if track.kind == "overlay":
            w = max(2, round(W * c.scale / 2) * 2)
            chain += [f"scale={w}:-2", "format=yuva420p"]
            pos = f"x=(main_w-overlay_w)*{_f(c.x)}:y=(main_h-overlay_h)*{_f(c.y)}"
        else:
            chain += [f"scale={W}:{H}:force_original_aspect_ratio=decrease", "format=yuva420p",
                      f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black@0", "setsar=1"]
            pos = "x=0:y=0"
        if c.opacity < 1:
            chain.append(f"colorchannelmixer=aa={_f(c.opacity)}")
        if c.fade_in > 0:
            chain.append(f"fade=t=in:st=0:d={_f(c.fade_in)}:alpha=1")
        if c.fade_out > 0:
            chain.append(f"fade=t=out:st={_f(max(0.0, c.duration - c.fade_out))}:d={_f(c.fade_out)}:alpha=1")
        chain.append(f"setpts=PTS+{_f(c.start)}/TB")
        graph.append(f"[{idx}:v]{','.join(chain)}[v{k}]")
        graph.append(f"[{prev}][v{k}]overlay={pos}:eof_action=pass:{_enable(c.start, c.end)}[o{k}]")
        prev = f"o{k}"

    text_clips = _text_clips(project)
    use_cues = project.burn_subtitles and bool(project.cues)
    ass_text = None
    tail = []
    if use_cues or text_clips:
        ass_text = build_ass(project, include_cues=use_cues, text_clips=text_clips)
        tail.append(f"ass={ASS_NAME}")
    tail.append("format=yuv420p")
    graph.append(f"[{prev}]{','.join(tail)}[vout]")

    # -- sound
    a_labels = []
    keys: list[str] = []
    voices = {id(c) for t in project.tracks if t.role == "voice" for c in t.clips}
    ducking = any(t.role == "ducked" and t.clips for t in project.tracks)
    for k, (c, gain, slot) in enumerate(_audio_sources(project)):
        if slot is None:
            pre = ["-stream_loop", "-1"] if c.loop else []
            idx = add_input([*pre, "-ss", _f(c.in_point), "-t", _f(c.duration), "-i", c.path])
            sources.append(c.path)
        else:
            idx = video_slot[id(c)]
        chain = [f"atrim=duration={_f(c.duration)}", "asetpts=PTS-STARTPTS",
                 "aformat=sample_rates=48000:channel_layouts=stereo"]
        if c.fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={_f(c.fade_in)}")
        if c.fade_out > 0:
            chain.append(f"afade=t=out:st={_f(max(0.0, c.duration - c.fade_out))}:d={_f(c.fade_out)}")
        if gain != 1:
            chain.append(f"volume={_f(gain)}")
        if c.start > 0:
            chain.append(f"adelay={round(c.start * 1000)}:all=1")
        graph.append(f"[{idx}:a]{','.join(chain)}[a{k}]")
        a_labels.append(f"[a{k}]")
        if slot is None and id(c) in voices and ducking:
            # Its own decode: an asplit into the sidechain stalls ffmpeg before the first frame.
            pre = ["-stream_loop", "-1"] if c.loop else []
            key = add_input([*pre, "-ss", _f(c.in_point), "-t", _f(c.duration), "-i", c.path])
            graph.append(f"[{key}:a]{','.join(chain)}[key{k}]")
            keys.append(f"[key{k}]")
    a_labels = _duck(project, a_labels, keys, graph)
    maps = ["-map", "[vout]"]
    out = ["-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf),
           "-pix_fmt", "yuv420p", "-r", str(fps)]
    if a_labels:
        mix = (f"{''.join(a_labels)}amix=inputs={len(a_labels)}:normalize=0:dropout_transition=0,"
               if len(a_labels) > 1 else f"{a_labels[0]}")
        level = f",loudnorm=I={_f(project.loudness)}:TP=-1.5:LRA=11,aresample=48000" if project.loudness is not None else ""
        # apad=whole_dur, not a bare apad: an endless audio branch makes ffmpeg 9 busy-spin with no
        # output on ~1 in 3 runs (stuck at 100% CPU, no progress line). Pad to the length, stay finite.
        graph.append(f"{mix}apad=whole_dur={_f(total)},atrim=0:{_f(total)}{level}[aout]")
        maps += ["-map", "[aout]"]
        out += ["-c:a", "aac", "-b:a", settings.audio_bitrate]
    else:
        out += ["-an"]
    out += ["-t", _f(total), "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out_path)]

    srt = write_srt(project.cues) if settings.write_srt and project.cues else None
    return ExportPlan(inputs, ";".join(graph), maps, out, total, ass_text, srt, sources)


# ---- running ----------------------------------------------------------------
_PROGRESS_US = re.compile(r"^out_time_(?:us|ms)=(\d+)$")
_PROGRESS_TS = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$")


def parse_progress(line: str) -> float | None:
    """Seconds encoded so far from one `-progress` line, else None."""
    line = line.strip()
    m = _PROGRESS_US.match(line)
    if m:
        return int(m.group(1)) / 1_000_000
    m = _PROGRESS_TS.match(line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


def _tail(path: Path, n: int = 12) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def run_export(exe: str, plan: ExportPlan, workdir: str | Path,
               on_progress: Callable[[float], None] = lambda f: None,
               should_stop: Callable[[], bool] = lambda: False,
               popen=subprocess.Popen, stall_seconds: float | None = 120.0) -> Path:
    """Run the plan. Writes subs/graph into ``workdir`` (ffmpeg runs there, so the ass filter
    gets a bare file name and no Windows-path escaping). Returns the output path.

    ``stall_seconds``: if ffmpeg prints no line at all for that long it is killed and
    ExportError is raised (None turns the watchdog off)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(plan.output[-1])
    if plan.ass_text is not None:
        (workdir / ASS_NAME).write_text(plan.ass_text, encoding="utf-8")
    graph_file = None
    if len(plan.graph) > GRAPH_INLINE_LIMIT:
        (workdir / GRAPH_NAME).write_text(plan.graph, encoding="utf-8")
        graph_file = GRAPH_NAME
    cmd = [exe, *plan.args(graph_file)]
    log_path = workdir / "ffmpeg.log"
    log.info("Export: %s", subprocess.list2cmdline(cmd)[:2000])

    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
        proc = popen(cmd, cwd=str(workdir), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=log_file, text=True, encoding="utf-8", errors="replace",
                     creationflags=_NO_WINDOW)
        # stdout is read on a helper thread so a stop request is seen within ~0.2 s even
        # while ffmpeg is quiet (opening many inputs prints no progress for a while)
        lines: queue.Queue = queue.Queue()

        def pump():
            for ln in proc.stdout:
                lines.put(ln)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        cancelled = False
        stalled = False
        last_line = time.monotonic()
        while True:
            if should_stop():
                cancelled = True
                break
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                if stall_seconds is not None and time.monotonic() - last_line > stall_seconds:
                    stalled = True
                    break
                continue
            last_line = time.monotonic()
            if line is None:
                break
            t = parse_progress(line)
            if t is not None and plan.duration > 0:
                on_progress(min(1.0, t / plan.duration))
        if cancelled:
            _stop(proc)
        elif stalled:
            _kill(proc)
        code = proc.wait()

    if stalled:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ExportError(f"ffmpeg stalled: no progress for {stall_seconds:g} s, killed.\n{_tail(log_path)}")

    if cancelled:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ExportCancelled("Export cancelled.")
    if code != 0:
        raise ExportError(f"ffmpeg exited with code {code}.\n{_tail(log_path)}")
    if plan.srt_text:
        out_path.with_suffix(".srt").write_text(plan.srt_text, encoding="utf-8")
    on_progress(1.0)
    return out_path


def _stop(proc) -> None:
    """Ask ffmpeg to quit ('q' on stdin), kill it if it doesn't."""
    try:
        proc.stdin.write("q\n")
        proc.stdin.flush()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def _kill(proc) -> None:
    try:
        proc.kill()
    except OSError:
        pass


def default_workdir() -> Path:
    from src.config import app_data_dir

    return app_data_dir() / "editor" / "export"


def ensure_clean(path: Path) -> None:
    for name in (ASS_NAME, GRAPH_NAME):
        try:
            (path / name).unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "ExportCancelled", "ExportError", "ExportPlan", "ExportSettings", "MediaInfo", "SETTINGS_KEY",
    "build_export", "default_workdir", "ffmpeg_version", "find_ffmpeg", "missing_sources",
    "parse_probe", "parse_progress", "probe", "run_export",
]
