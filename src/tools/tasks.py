"""Tool providers: plug the slicer, frame extractor and upscaler into the Phase 2 JobQueue.

One ``Job`` = one input file (``job.refs[0]``). A tool writes its files
straight to disk (videos are too big to hold as ``OutputFile`` bytes), so
``generate`` returns nothing and the page's saver calls ``take_outputs``.
Options come from the page: every config value plus ``out_dir``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from src.gen.models import Job, OutputFile
from src.gen.output import unique_path
from src.gen.provider import Provider, ProviderError, RunContext
from src.i18n import tr
from src.tools import binaries, ffmpeg, realesrgan, runner

log = logging.getLogger(__name__)

TOOL_NAMES = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "realesrgan": "Real-ESRGAN"}


def missing_message(tools: list[str]) -> str:
    names = ", ".join(TOOL_NAMES.get(t, t) for t in tools)
    return tr("tools_missing", names=names)


class ToolProvider(Provider):
    """Base: resolves binaries per job, runs commands, hands back written paths."""

    needs: tuple[str, ...] = ()

    def __init__(self, store=None, run=None, capture=None, which=None):
        self.store = store
        self._run = run or runner.run_command
        self._capture = capture or runner.capture
        self._which = which
        self._outputs: dict[int, list[Path]] = {}
        self._lock = threading.Lock()

    # ---- binaries -----------------------------------------------------
    def find(self, tool: str) -> Path | None:
        if self._which is not None:
            return binaries.find_binary(tool, self.store, self._which)
        return binaries.find_binary(tool, self.store)

    def missing(self) -> list[str]:
        return [t for t in self.needs if self.find(t) is None]

    def _require(self) -> dict[str, Path]:
        missing = self.missing()
        if missing:
            raise ProviderError(missing_message(missing))
        return {t: self.find(t) for t in self.needs}

    # ---- queue glue ---------------------------------------------------
    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        if not job.refs:
            raise ProviderError(tr("tools_no_input"))
        src = Path(job.refs[0])
        if not src.is_file():
            raise ProviderError(tr("tools_input_gone", path=src.name))
        bins = self._require()
        out_dir = Path(options.get("out_dir") or src.parent)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = self.process(src, out_dir, options, bins, ctx)
        with self._lock:
            self._outputs[job.id] = paths
        return []

    def take_outputs(self, job: Job, files=None) -> list[Path]:
        """Saver for ``JobQueue``: the paths ``generate`` wrote for this job."""
        with self._lock:
            return self._outputs.pop(job.id, [])

    def process(self, src: Path, out_dir: Path, options: dict[str, Any],
                bins: dict[str, Path], ctx: RunContext) -> list[Path]:
        raise NotImplementedError

    # ---- helpers ------------------------------------------------------
    def _probe(self, bins: dict[str, Path], src: Path) -> ffmpeg.MediaInfo:
        return ffmpeg.probe(bins["ffprobe"], src, self._capture)

    def _ffmpeg(self, cmd: list[str], ctx: RunContext, on_seconds: Callable[[float], None]) -> None:
        def on_line(line: str) -> None:
            secs = ffmpeg.progress_seconds(line)
            if secs is not None:
                on_seconds(secs)

        self._run(cmd, on_line=on_line, should_stop=ctx.should_stop)


def _new_folder(path: Path) -> Path:
    path = unique_path(path)
    path.mkdir(parents=True)
    return path


class SlicerProvider(ToolProvider):
    key = "video_slicer"
    name = "Video slicer (ffmpeg)"
    needs = ("ffmpeg", "ffprobe")

    def process(self, src, out_dir, options, bins, ctx):
        info = self._probe(bins, src)
        try:
            segments = ffmpeg.plan_segments(
                options.get("slice_mode", "duration"), info.duration,
                seconds=float(options.get("segment_seconds", 10)),
                parts=int(options.get("parts", 2)), ranges=options.get("ranges", ""))
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        encode = options.get("encode", "copy")
        folder = _new_folder(out_dir / f"{src.stem}_slices")
        ext = ffmpeg.slice_ext(src, encode)
        total = sum(s.length for s in segments) or 1.0
        done = 0.0
        paths = []
        for i, seg in enumerate(segments, 1):
            dst = folder / ffmpeg.segment_name(src.stem, i, seg, ext)
            base = done
            self._ffmpeg(ffmpeg.slice_cmd(bins["ffmpeg"], src, seg, dst, encode,
                                          int(options.get("crf", 18))),
                         ctx, lambda s, base=base, seg=seg: ctx.progress((base + min(s, seg.length)) / total))
            done += seg.length
            ctx.progress(done / total)
            if dst.exists():
                paths.append(dst)
        if not paths:
            raise ProviderError(tr("tools_no_output"))
        log.info("Sliced %s into %d part(s) -> %s", src.name, len(paths), folder)
        return paths


class FrameExtractorProvider(ToolProvider):
    key = "frame_extractor"
    name = "Frame extractor (ffmpeg)"
    needs = ("ffmpeg", "ffprobe")

    def process(self, src, out_dir, options, bins, ctx):
        info = self._probe(bins, src)
        mode = options.get("frame_mode", "interval")
        fmt = options.get("frame_format", "png")
        quality = int(options.get("jpg_quality", 92))
        folder = _new_folder(out_dir / f"{src.stem}_frames")
        exe = bins["ffmpeg"]
        duration = info.duration or 1.0
        try:
            if mode in ("interval", "all"):
                cmd = ffmpeg.frames_sequence_cmd(exe, src, folder, src.stem, mode,
                                                 float(options.get("interval", 1.0)), fmt, quality)
                self._ffmpeg(cmd, ctx, lambda s: ctx.progress(min(s / duration, 0.99)))
            elif mode == "first":
                self._ffmpeg(ffmpeg.frame_at_cmd(exe, src, 0.0, folder / f"{src.stem}_first.{fmt}",
                                                 fmt, quality), ctx, lambda s: None)
            elif mode == "last":
                self._ffmpeg(ffmpeg.last_frame_cmd(exe, src, folder / f"{src.stem}_last.{fmt}", fmt,
                                                   quality), ctx, lambda s: None)
            elif mode in ("count", "times"):
                if mode == "count":
                    times = ffmpeg.evenly_spaced(info.duration, int(options.get("frame_count", 10)))
                else:
                    times = ffmpeg.parse_times(options.get("timestamps", ""), info.duration)
                for i, t in enumerate(times, 1):
                    dst = folder / f"{src.stem}_{i:03d}_{ffmpeg.label_time(t)}.{fmt}"
                    self._ffmpeg(ffmpeg.frame_at_cmd(exe, src, t, dst, fmt, quality), ctx, lambda s: None)
                    ctx.progress(i / len(times))
            else:
                raise ProviderError(f"unknown frame mode: {mode}")
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc
        paths = sorted(p for p in folder.iterdir() if p.is_file())
        if not paths:
            raise ProviderError(tr("tools_no_output"))
        log.info("Extracted %d frame(s) from %s -> %s", len(paths), src.name, folder)
        return paths


class UpscaleProvider(ToolProvider):
    key = "upscaler"
    name = "Real-ESRGAN upscaler"
    needs = ("realesrgan",)

    def process(self, src, out_dir, options, bins, ctx):
        model = options.get("model", "realesrgan-x4plus")
        scale = realesrgan.check_scale(model, int(options.get("scale", 4)))
        fmt = options.get("out_format", "png")
        dst = unique_path(out_dir / realesrgan.output_name(src, scale, fmt))
        exe = bins["realesrgan"]
        cmd = realesrgan.upscale_cmd(exe, src, dst, model, scale, fmt,
                                     int(options.get("tile", 0)), bool(options.get("tta", False)),
                                     str(options.get("gpu", "auto")))

        def on_line(line: str) -> None:
            frac = realesrgan.progress_fraction(line)
            if frac is not None:
                ctx.progress(min(frac, 0.99))

        # cwd = the exe's folder so it also finds ``models`` if -m isn't passed.
        self._run(cmd, on_line=on_line, should_stop=ctx.should_stop, cwd=exe.parent)
        if not dst.exists():
            raise ProviderError(tr("tools_no_output"))
        log.info("Upscaled %s -> %s", src.name, dst)
        return [dst]
