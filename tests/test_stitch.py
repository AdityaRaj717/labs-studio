"""The stitcher with real FFmpeg on tiny generated media. Skips where FFmpeg isn't found."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.editor import stitch as stitch_module
from src.editor.ffmpeg import ExportCancelled, ExportError, probe
from src.editor.stitch import FfmpegNotFound, StitchSpec, resolve_ffmpeg, stitch

try:
    EXE = resolve_ffmpeg()
except FfmpegNotFound:
    pytest.skip("no FFmpeg here", allow_module_level=True)


def ff(*args) -> str:
    done = subprocess.run([EXE, "-hide_banner", "-y", *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stderr[-800:]
    return done.stderr


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", d / "wide.mp4")
    ff("-f", "lavfi", "-i", "testsrc=s=180x320:r=30:d=2", "-pix_fmt", "yuv420p", d / "tall.mp4")
    ff("-f", "lavfi", "-i", "sine=f=440:d=2", "-af", "volume=0.5", d / "voice.wav")
    ff("-f", "lavfi", "-i", "sine=f=220:d=6", "-af", "volume=0.5", d / "bgm.wav")
    return d


def run(tmp_path, media, **kw):
    spec = {"clips": [{"path": str(media / "wide.mp4")}], "size": (320, 180), "output": str(tmp_path / "out.mp4"), **kw}
    return stitch(StitchSpec.from_dict(spec))


def mean_db(path, start, length):  # under 300 Hz: the 220 Hz music without the 440 Hz voice
    text = ff("-ss", start, "-t", length, "-i", path, "-af", "lowpass=f=300,lowpass=f=300,volumedetect", "-f", "null", "-")
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", text).group(1))


def test_two_clips_join_with_correct_duration(tmp_path, media):
    out = run(tmp_path, media, clips=[{"path": str(media / "wide.mp4")}, {"path": str(media / "wide.mp4"), "trim_start": 0.5}])
    assert probe(EXE, out).duration == pytest.approx(3.5, abs=0.15)


def test_hold_extends_a_clip_and_a_fade_overlaps(tmp_path, media):
    out = run(tmp_path, media, clips=[{"path": str(media / "wide.mp4"), "hold": 1}])
    assert probe(EXE, out).duration == pytest.approx(3.0, abs=0.15)
    both = [{"path": str(media / "wide.mp4")}] * 2
    out = run(tmp_path, media, clips=both, transition={"type": "fade", "duration": 0.5})
    assert probe(EXE, out).duration == pytest.approx(3.5, abs=0.15)


def test_mixed_ratios_are_letterboxed_to_spec_size(tmp_path, media):
    out = run(tmp_path, media, clips=[{"path": str(media / "wide.mp4")}, {"path": str(media / "tall.mp4")}], size="640x360")
    assert (probe(EXE, out).width, probe(EXE, out).height) == (640, 360)
    frame = tmp_path / "f.png"
    ff("-ss", "3", "-i", out, "-frames:v", "1", "-vf", "crop=40:360:0:0", frame)
    assert frame.stat().st_size < 2000  # the left edge is flat black: the bars


def test_silent_clip_plus_voice_has_audio(tmp_path, media):
    out = run(tmp_path, media, voice=[{"path": str(media / "voice.wav"), "start": 0}])
    assert probe(EXE, out).has_audio


def test_bgm_ducks_under_voice(tmp_path, media):
    clips = [{"path": str(media / "wide.mp4")}] * 3
    out = run(tmp_path, media, clips=clips, loudness=None, voice=[{"path": str(media / "voice.wav"), "start": 2}],
              bgm={"path": str(media / "bgm.wav"), "volume": 0.5, "duck": True})
    flat = run(tmp_path, media, clips=clips, loudness=None, output=str(tmp_path / "flat.mp4"),
               voice=[{"path": str(media / "voice.wav"), "start": 2}], bgm={"path": str(media / "bgm.wav"), "volume": 0.5, "duck": False})
    # Measured against the same mix undeducked: outside the voice nothing moves, during it the mix is lower.
    assert mean_db(out, 0.3, 1.2) == pytest.approx(mean_db(flat, 0.3, 1.2), abs=1.0)
    assert mean_db(out, 2.5, 1.0) < mean_db(flat, 2.5, 1.0) - 1.0


def test_loudness_is_within_1_lu_of_target(tmp_path, media):
    clips = [{"path": str(media / "wide.mp4")}] * 8
    out = run(tmp_path, media, clips=clips, bgm={"path": str(media / "bgm.wav"), "duck": False})
    text = ff("-i", out, "-af", "ebur128=peak=true", "-f", "null", "-")
    measured = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", text)[-1])
    assert measured == pytest.approx(-14, abs=1.0)


def test_missing_input_lists_the_path(tmp_path, media):
    gone = str(tmp_path / "gone.mp4")
    with pytest.raises(ExportError, match="gone.mp4"):
        run(tmp_path, media, clips=[{"path": gone}])
    with pytest.raises(ExportError, match="no-voice.wav"):
        run(tmp_path, media, voice=[{"path": str(tmp_path / "no-voice.wav")}])


def test_ffmpeg_not_found_has_install_step(monkeypatch):
    monkeypatch.setattr(stitch_module, "find_ffmpeg", lambda *_: None)
    with pytest.raises(FfmpegNotFound, match="Install"):
        resolve_ffmpeg()


def test_ffmpeg_order_is_setting_env_path_folder(monkeypatch):
    asked = []
    monkeypatch.setenv("FFMPEG_PATH", "from-env")
    monkeypatch.setattr(stitch_module, "find_ffmpeg", lambda c=None: asked.append(c))
    with pytest.raises(FfmpegNotFound):
        resolve_ffmpeg("from-setting")
    assert asked == ["from-setting", str(stitch_module.FALLBACK_FFMPEG)]
    asked.clear()
    with pytest.raises(FfmpegNotFound):
        resolve_ffmpeg()
    assert asked == ["from-env", str(stitch_module.FALLBACK_FFMPEG)]


def test_originals_are_untouched(tmp_path, media):
    digest = lambda: hashlib.sha256((media / "wide.mp4").read_bytes()).hexdigest()  # noqa: E731
    before = digest()
    run(tmp_path, media)
    assert digest() == before
    with pytest.raises(ExportError, match="overwrite"):
        run(tmp_path, media, output=str(media / "wide.mp4"))
    assert digest() == before


def test_cancel_removes_partial_output(tmp_path, media):
    out = tmp_path / "out.mp4"
    with pytest.raises(ExportCancelled):
        stitch(StitchSpec.from_dict({"clips": [{"path": str(media / "wide.mp4")}] * 20, "output": str(out)}), should_stop=lambda: True)
    assert not out.exists()


def test_cli_prints_json_progress_and_the_file(tmp_path, media):
    spec = tmp_path / "spec.json"
    out = tmp_path / "cli.mp4"
    spec.write_text(json.dumps({"clips": [{"path": str(media / "wide.mp4")}], "size": "320x180", "output": str(out)}))
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen([sys.executable, "-m", "src.stitch_cli", str(spec)], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    stdout = proc.stdout.read()  # stdin stays open: closing it means cancel
    proc.stdin.close()
    assert proc.wait(10) == 0
    lines = [json.loads(line) for line in stdout.splitlines()]
    assert lines[-1] == {"type": "done", "file": str(out)} and out.exists()
    assert any(line["type"] == "progress" for line in lines)
