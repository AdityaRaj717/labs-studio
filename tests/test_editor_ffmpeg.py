"""ffmpeg locate / probe / command builder / runner, with subprocess mocked."""

from __future__ import annotations

import io
import subprocess
from types import SimpleNamespace

import pytest

from src.editor import ffmpeg as ff
from src.editor.model import Clip, Cue, Project


def _project() -> Project:
    p = Project.new(width=1280, height=720, fps=30, background="#102030")
    v = p.first_track("video")
    v.clips += [Clip("image", "C:/m/a.png", start=0, duration=3, fade_in=0.5),
                Clip("video", "C:/m/v.mp4", start=2.5, duration=4, in_point=1, has_audio=True, volume=0.5,
                     fade_in=0.5, fade_out=1)]
    ov = p.first_track("overlay")
    ov.clips += [Clip("image", "C:/m/logo.png", start=1, duration=2, x=1, y=0, scale=0.2, opacity=0.5),
                 Clip("text", text="Title", start=0, duration=2)]
    a = p.first_track("audio")
    a.volume = 0.5
    a.clips.append(Clip("audio", "C:/m/music.mp3", start=0, duration=6.5, loop=True, fade_out=2))
    p.cues = [Cue(0.5, 2, "hello")]
    return p


# ---- locate / probe -------------------------------------------------------------
def test_find_ffmpeg_prefers_configured(tmp_path):
    exe = tmp_path / "bin" / "ffmpeg.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert ff.find_ffmpeg(str(exe), which=lambda n: "PATH") == str(exe)
    assert ff.find_ffmpeg(str(tmp_path), which=lambda n: "PATH") == str(exe)  # folder with bin/
    assert ff.find_ffmpeg(f'"{exe.parent}"', which=lambda n: "PATH") == str(exe)
    assert ff.find_ffmpeg(str(tmp_path / "nope.exe"), which=lambda n: "PATH") == "PATH"
    assert ff.find_ffmpeg("", which=lambda n: None) is None


def test_ffmpeg_version():
    run = lambda *a, **k: SimpleNamespace(stdout="ffmpeg version 9.0.2-full_build Copyright", stderr="")
    assert ff.ffmpeg_version("ffmpeg", run=run) == "9.0.2-full_build"

    def boom(*a, **k):
        raise FileNotFoundError

    assert ff.ffmpeg_version("ffmpeg", run=boom) is None


PROBE = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'v.mp4':
  Duration: 00:01:02.50, start: 0.000000, bitrate: 1000 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 30 fps
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s
At least one output file must be specified
"""


def test_parse_probe():
    info = ff.parse_probe(PROBE)
    assert (info.duration, info.has_video, info.has_audio, info.width, info.height) == (62.5, True, True, 1920, 1080)
    img = ff.parse_probe("  Duration: N/A, bitrate: N/A\n  Stream #0:0: Video: png, rgb24(pc), 800x600, 25 tbr")
    assert img.duration == 0 and img.has_video and not img.has_audio
    mp3 = ff.parse_probe("  Duration: 00:00:04.00\n  Stream #0:0: Audio: mp3\n  Stream #0:1: Video: mjpeg, 300x300 (attached pic)")
    assert mp3.has_audio and not mp3.has_video


def test_probe_calls_ffmpeg_i():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout="", stderr=PROBE)

    assert ff.probe("ffm", "x.mp4", run=run).duration == 62.5
    assert seen["cmd"] == ["ffm", "-hide_banner", "-i", "x.mp4"]


# ---- builder ----------------------------------------------------------------------
def test_build_export_inputs():
    plan = ff.build_export(_project(), "out.mp4")
    i = plan.inputs
    assert i[:4] == ["-f", "lavfi", "-i", "color=c=0x102030:s=1280x720:r=30:d=6.5"]
    assert ["-loop", "1", "-framerate", "30", "-t", "3", "-i", "C:/m/a.png"] == i[4:12]
    assert ["-ss", "1", "-t", "4", "-i", "C:/m/v.mp4"] == i[12:18]
    assert ["-stream_loop", "-1", "-ss", "0", "-t", "6.5", "-i", "C:/m/music.mp3"] == i[-8:]
    assert plan.duration == 6.5
    assert plan.sources == ["C:/m/a.png", "C:/m/v.mp4", "C:/m/logo.png", "C:/m/music.mp3"]


def test_build_export_graph():
    plan = ff.build_export(_project(), "out.mp4")
    parts = plan.graph.split(";")
    # base track: fit + pad, alpha crossfade, shifted to its start
    assert parts[0].startswith("[1:v]fps=30,trim=duration=3,setpts=PTS-STARTPTS,"
                               "scale=1280:720:force_original_aspect_ratio=decrease")
    assert "fade=t=in:st=0:d=0.5:alpha=1" in parts[0] and parts[0].endswith("setpts=PTS+0/TB[v0]")
    assert parts[1] == "[0:v][v0]overlay=x=0:y=0:eof_action=pass:enable='between(t,0,3)'[o0]"
    assert "fade=t=out:st=3:d=1:alpha=1,setpts=PTS+2.5/TB[v1]" in parts[2]
    # overlay track: scaled to 20% width, half opacity, top-right
    assert "scale=256:-2" in parts[4] and "colorchannelmixer=aa=0.5" in parts[4]
    assert parts[5] == ("[o1][v2]overlay=x=(main_w-overlay_w)*1:y=(main_h-overlay_h)*0:"
                        "eof_action=pass:enable='between(t,1,3)'[o2]")
    assert parts[6] == "[o2]ass=subs.ass,format=yuv420p[vout]"
    # audio: video clip's own sound (input 2) + looped music, mixed without normalising
    assert parts[7].startswith("[2:a]atrim=duration=4") and "volume=0.5" in parts[7] and "adelay=2500:all=1" in parts[7]
    assert parts[8].startswith("[4:a]") and "afade=t=out:st=4.5:d=2" in parts[8] and "volume=0.5" in parts[8]
    assert parts[9] == "[a0][a1]amix=inputs=2:normalize=0:dropout_transition=0,apad=whole_dur=6.5,atrim=0:6.5[aout]"
    assert "TITLE" not in plan.ass_text and "Title" in plan.ass_text and "hello" in plan.ass_text


def test_build_export_output_args():
    plan = ff.build_export(_project(), "D:/out/x.mp4", ff.ExportSettings(crf=18, preset="slow"))
    args = plan.args()
    assert args[:2] == ["-hide_banner", "-y"]
    assert args[args.index("-filter_complex") + 1] == plan.graph
    assert plan.maps == ["-map", "[vout]", "-map", "[aout]"]
    for a, b in [("-crf", "18"), ("-preset", "slow"), ("-c:a", "aac"), ("-t", "6.5"), ("-progress", "pipe:1")]:
        assert plan.output[plan.output.index(a) + 1] == b
    assert args[-1] == "D:/out/x.mp4"
    file_args = plan.args("graph.txt")
    assert file_args[file_args.index("-/filter_complex") + 1] == "graph.txt"
    assert "-filter_complex" not in file_args


def test_hidden_and_muted_tracks_and_no_audio():
    p = _project()
    p.first_track("audio").muted = True
    p.first_track("overlay").hidden = True
    p.first_track("video").clips[1].has_audio = False
    p.burn_subtitles = False
    plan = ff.build_export(p, "o.mp4")
    assert "music.mp3" not in plan.inputs and "C:/m/logo.png" not in plan.inputs
    assert "-an" in plan.output and "[aout]" not in plan.maps
    assert plan.ass_text is None and "ass=" not in plan.graph
    assert plan.graph.endswith("[o1]format=yuv420p[vout]")


def test_single_audio_source_skips_amix_and_srt_sidecar():
    p = Project.new()
    p.first_track("video").clips.append(Clip("image", "a.png", duration=2))
    p.first_track("audio").clips.append(Clip("audio", "m.mp3", start=0.5, duration=1.5))
    p.cues = [Cue(0, 1, "x")]
    plan = ff.build_export(p, "o.mp4", ff.ExportSettings(write_srt=True))
    assert "amix" not in plan.graph and "[a0]apad=whole_dur=2,atrim=0:2[aout]" in plan.graph
    assert plan.srt_text.startswith("1\n00:00:00,000 --> 00:00:01,000\nx")


def test_empty_project_raises():
    with pytest.raises(ff.ExportError):
        ff.build_export(Project.new(), "o.mp4")


def test_missing_sources(tmp_path):
    p = Project.new()
    (tmp_path / "a.png").write_bytes(b"x")
    p.first_track("video").clips += [Clip("image", str(tmp_path / "a.png")), Clip("image", str(tmp_path / "b.png"))]
    p.first_track("overlay").clips.append(Clip("text", text="t"))
    assert ff.missing_sources(p) == [str(tmp_path / "b.png")]


# ---- progress / runner ----------------------------------------------------------------
def test_parse_progress():
    assert ff.parse_progress("out_time_us=2500000\n") == 2.5
    assert ff.parse_progress("out_time_ms=1000000") == 1.0
    assert ff.parse_progress("out_time=00:01:02.500000") == 62.5
    assert ff.parse_progress("frame=10") is None
    assert ff.parse_progress("out_time=N/A") is None


class FakeProc:
    def __init__(self, lines, code=0, on_wait=None):
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))
        self.stdin = io.StringIO()
        self.code = code
        self.killed = False

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.killed = True


def _plan(tmp_path, project=None):
    return ff.build_export(project or _project(), str(tmp_path / "out.mp4"), ff.ExportSettings(write_srt=True))


def test_run_export_reports_progress_and_writes_files(tmp_path):
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        (tmp_path / "out.mp4").write_bytes(b"mp4")
        return FakeProc(["frame=1", "out_time_us=3250000", "out_time_us=6500000", "progress=end"])

    progress = []
    plan = _plan(tmp_path)
    out = ff.run_export("ffm", plan, tmp_path / "work", on_progress=progress.append, popen=popen)
    assert out == tmp_path / "out.mp4"
    assert progress == [0.5, 1.0, 1.0]
    assert seen["cmd"][0] == "ffm" and seen["kw"]["cwd"] == str(tmp_path / "work")
    assert (tmp_path / "work" / "subs.ass").read_text(encoding="utf-8") == plan.ass_text
    assert (tmp_path / "out.srt").read_text(encoding="utf-8").startswith("1\n")


def test_run_export_long_graph_goes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ff, "GRAPH_INLINE_LIMIT", 10)
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc([])

    plan = _plan(tmp_path)
    ff.run_export("ffm", plan, tmp_path / "w", popen=popen)
    assert seen["cmd"][seen["cmd"].index("-/filter_complex") + 1] == "graph.txt"
    assert (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8") == plan.graph


def test_run_export_failure_includes_log_tail(tmp_path):
    def popen(cmd, stderr=None, **kw):
        stderr.write("line\n[ass] Error opening font\n")
        stderr.flush()
        return FakeProc([], code=1)

    with pytest.raises(ff.ExportError, match="code 1(.|\n)*Error opening font"):
        ff.run_export("ffm", _plan(tmp_path), tmp_path / "w", popen=popen)


def test_run_export_cancel_sends_q_and_removes_partial(tmp_path):
    procs = []

    def popen(cmd, **kw):
        (tmp_path / "out.mp4").write_bytes(b"partial")
        procs.append(FakeProc(["out_time_us=1000000"] * 50))
        return procs[0]

    calls = iter([False, True])
    with pytest.raises(ff.ExportCancelled):
        ff.run_export("ffm", _plan(tmp_path), tmp_path / "w", should_stop=lambda: next(calls, True), popen=popen)
    assert procs[0].stdin.getvalue() == "q\n"
    assert not (tmp_path / "out.mp4").exists()


def test_stop_kills_when_q_is_ignored():
    class Stubborn(FakeProc):
        def wait(self, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            return 0

    p = Stubborn([])
    ff._stop(p)
    assert p.killed
