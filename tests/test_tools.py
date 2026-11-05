"""Binary discovery, ffmpeg commands and the runner. No real process is started: the runner gets a fake Popen."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from src.config import Settings
from src.gen.models import Job
from src.gen.provider import ProviderError, RunContext, StopRequested
from src.tools import binaries, ffmpeg, runner


def probe_json(duration=25.0, fps="30/1", audio=True) -> str:
    streams = [{"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": fps}]
    if audio:
        streams.append({"codec_type": "audio"})
    return json.dumps({"streams": streams, "format": {"duration": str(duration)}})


class FakeRun:
    """Stands in for ``runner.run_command``: records commands, writes their output files."""

    def __init__(self, lines=(), fail=False, frames=3):
        self.cmds: list[list[str]] = []
        self.lines = list(lines)
        self.fail = fail
        self.frames = frames
        self.kwargs: list[dict] = []

    def __call__(self, cmd, on_line=None, should_stop=lambda: False, cwd=None):
        cmd = [str(c) for c in cmd]
        self.cmds.append(cmd)
        self.kwargs.append({"cwd": cwd})
        if self.fail:
            raise ProviderError("ffmpeg exited with code 1: boom")
        for line in self.lines:
            on_line and on_line(line)
        out = cmd[cmd.index("-o") + 1] if "-o" in cmd else cmd[-1]
        if "%06d" in out:
            for i in range(1, self.frames + 1):
                Path(out.replace("%06d", f"{i:06d}")).write_bytes(b"x")
        else:
            Path(out).write_bytes(b"x")
        return []


def ctx(progress=None, stop=lambda: False) -> RunContext:
    return RunContext(progress=progress or (lambda p: None), should_stop=stop)


@pytest.fixture
def store(tmp_path):
    return Settings(tmp_path / "settings.json")


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "in" / "clip.mp4"
    p.parent.mkdir()
    p.write_bytes(b"fake")
    return p


def which_all(name):
    return f"C:/bin/{name}.exe"


# ---- binaries -----------------------------------------------------------
def test_find_binary_prefers_settings_then_path(store, tmp_path):
    assert binaries.find_binary("ffmpeg", store, which=lambda n: None) is None
    assert binaries.find_binary("ffmpeg", store, which=which_all) == Path("C:/bin/ffmpeg.exe")
    exe = tmp_path / "tools" / "ffmpeg.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    store.set("tools.ffmpeg_path", str(exe))
    assert binaries.find_binary("ffmpeg", store, which=which_all) == exe


def test_find_binary_accepts_folder_and_ffprobe_next_to_ffmpeg(store, tmp_path, monkeypatch):
    monkeypatch.setattr(binaries.sys, "platform", "win32")
    folder = tmp_path / "ff"
    folder.mkdir()
    (folder / "ffmpeg.exe").write_bytes(b"")
    (folder / "ffprobe.exe").write_bytes(b"")
    store.set("tools.ffmpeg_path", str(folder))
    assert binaries.find_binary("ffmpeg", store, which=lambda n: None) == folder / "ffmpeg.exe"
    assert binaries.find_binary("ffprobe", store, which=lambda n: None) == folder / "ffprobe.exe"


def test_bad_configured_path_falls_back_to_path(store):
    store.set("tools.ffmpeg_path", "Z:/nope/ffmpeg.exe")
    assert binaries.find_binary("ffmpeg", store, which=which_all) == Path("C:/bin/ffmpeg.exe")
    assert binaries.missing(["ffmpeg"], store, which=lambda n: None) == ["ffmpeg"]


def test_parse_ranges_clamps_and_open_end():
    assert ffmpeg.parse_ranges("0:05-0:12, 1:00-", 80) == [(5, 12), (60, 80)]
    assert ffmpeg.parse_ranges("10-999", 30) == [(10, 30)]
    with pytest.raises(ValueError):
        ffmpeg.parse_ranges("20-10", 30)
    with pytest.raises(ValueError):
        ffmpeg.parse_ranges("  ", 30)


def test_plan_segments_modes():
    segs = ffmpeg.plan_segments("duration", 25, seconds=10)
    assert [(s.start, s.end) for s in segs] == [(0, 10), (10, 20), (20, 25)]
    # A 0.1 s sliver joins the previous piece.
    segs = ffmpeg.plan_segments("duration", 20.1, seconds=10)
    assert [(s.start, s.end) for s in segs] == [(0, 10), (10, 20.1)]
    segs = ffmpeg.plan_segments("parts", 30, parts=3)
    assert [(s.start, s.end) for s in segs] == [(0, 10), (10, 20), (20, 30)]
    assert len(ffmpeg.plan_segments("ranges", 30, ranges="1-2;3-4")) == 2
    with pytest.raises(ValueError):
        ffmpeg.plan_segments("duration", 0, seconds=10)


def test_slice_cmd_copy_vs_reencode(tmp_path):
    seg = ffmpeg.Segment(5, 15)
    copy = ffmpeg.slice_cmd(Path("ffmpeg"), Path("in.mp4"), seg, tmp_path / "o.mp4", "copy")
    assert copy[copy.index("-ss") + 1] == "0:00:05.000" and copy[copy.index("-t") + 1] == "0:00:10.000"
    assert "copy" in copy and "libx264" not in copy and "+faststart" in copy
    assert "make_zero" not in copy
    mkv = ffmpeg.slice_cmd(Path("ffmpeg"), Path("in.mkv"), seg, tmp_path / "o.mkv", "copy")
    assert "make_zero" in mkv
    enc = ffmpeg.slice_cmd(Path("ffmpeg"), Path("in.mkv"), seg, tmp_path / "o.mkv", "reencode", crf=20)
    assert enc[enc.index("-crf") + 1] == "20" and "+faststart" not in enc
    assert "-progress" in enc and enc[-1].endswith("o.mkv")
    assert ffmpeg.slice_ext(Path("a.MKV"), "copy") == ".mkv"
    assert ffmpeg.slice_ext(Path("a.mkv"), "reencode") == ".mp4"


def test_frame_cmds(tmp_path):
    seq = ffmpeg.frames_sequence_cmd(Path("ffmpeg"), Path("v.mp4"), tmp_path, "v", "interval", 2.5)
    assert "fps=1/2.5" in seq and seq[-1].endswith("v_%06d.png")
    allf = ffmpeg.frames_sequence_cmd(Path("ffmpeg"), Path("v.mp4"), tmp_path, "v", "all", fmt="jpg",
                                      jpg_quality=100)
    assert "passthrough" in allf and allf[allf.index("-q:v") + 1] == "2"
    one = ffmpeg.frame_at_cmd(Path("ffmpeg"), Path("v.mp4"), 3.0, tmp_path / "f.png")
    assert one[one.index("-frames:v") + 1] == "1"
    last = ffmpeg.last_frame_cmd(Path("ffmpeg"), Path("v.mp4"), tmp_path / "l.jpg", "jpg", 1)
    assert last[last.index("-sseof") + 1] == "-3" and last[last.index("-q:v") + 1] == "31"
    assert ffmpeg.evenly_spaced(10, 4) == [1.25, 3.75, 6.25, 8.75]
    assert ffmpeg.parse_times("0:01, 2.5 99", duration=10) == [1, 2.5, 9.95]


def test_parse_probe_and_progress():
    info = ffmpeg.parse_probe(probe_json(12.5, "30000/1001"))
    assert info.duration == 12.5 and info.width == 1280 and round(info.fps, 2) == 29.97 and info.has_audio
    with pytest.raises(ProviderError):
        ffmpeg.parse_probe(json.dumps({"streams": [{"codec_type": "audio"}]}))
    with pytest.raises(ProviderError):
        ffmpeg.parse_probe("not json")
    assert ffmpeg.progress_seconds("out_time_us=2500000") == 2.5
    assert ffmpeg.progress_seconds("out_time_ms=1000000") == 1.0
    assert ffmpeg.progress_seconds("out_time=00:01:02.500000") == 62.5
    assert ffmpeg.progress_seconds("frame=12") is None


# ---- runner ---------------------------------------------------------------
class FakeProc:
    def __init__(self, lines, code=0, block=False):
        self._lines = lines
        self.code = code
        self.killed = False
        self._release = threading.Event()
        if not block:
            self._release.set()
        self.stdout = self._iter()

    def _iter(self):
        yield from self._lines
        self._release.wait(5)

    def kill(self):
        self.killed = True
        self._release.set()

    def wait(self):
        self._release.wait(5)
        return -9 if self.killed else self.code


def test_run_command_streams_lines_and_raises_on_error():
    seen = []
    tail = runner.run_command(["ffmpeg", "-i", "x"], on_line=seen.append,
                              popen=lambda *a, **k: FakeProc(["out_time_us=1\n", "\n", "progress=end\n"]))
    assert seen == ["out_time_us=1", "progress=end"] and tail == seen
    with pytest.raises(ProviderError, match="code 1: Invalid data"):
        runner.run_command(["ffmpeg"], popen=lambda *a, **k: FakeProc(["Invalid data\n", "x=1\n"], code=1))


def test_run_command_kills_on_stop():
    proc = FakeProc(["out_time_us=1\n"], block=True)
    calls = iter([False, False, True])
    with pytest.raises(StopRequested):
        runner.run_command(["ffmpeg"], should_stop=lambda: next(calls, True), popen=lambda *a, **k: proc,
                           poll=0.01)
    assert proc.killed


def test_run_command_missing_exe():
    def boom(*a, **k):
        raise FileNotFoundError("nope")

    with pytest.raises(ProviderError, match="Could not start"):
        runner.run_command(["ffmpeg"], popen=boom)


def test_capture_returns_stdout_and_raises():
    class R:
        def __init__(self, code, out="", err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    assert runner.capture(["ffprobe"], run=lambda *a, **k: R(0, "{}")) == "{}"
    with pytest.raises(ProviderError, match="moov atom"):
        runner.capture(["ffprobe"], run=lambda *a, **k: R(1, err="x\nmoov atom not found"))


# ---- providers ------------------------------------------------------------
