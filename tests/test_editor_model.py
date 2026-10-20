"""Editor project model, subtitles and auto-edit (no Qt, no ffmpeg)."""

from __future__ import annotations

import pytest

from src.editor.autoedit import SlideshowOptions, build_slideshow, natural_key, scan_folder
from src.editor.ffmpeg import MediaInfo
from src.editor.model import Clip, Cue, Project, media_kind
from src.editor.subtitles import (
    ass_color, build_ass, format_ass_time, format_srt_time, load_subtitles, parse_ass, parse_srt,
    parse_srt_time, write_srt,
)


# ---- model -------------------------------------------------------------------
def test_new_project_has_three_tracks_and_zero_duration():
    p = Project.new()
    assert [t.kind for t in p.tracks] == ["video", "overlay", "audio"]
    assert p.duration == 0


def test_add_track_keeps_audio_last():
    p = Project.new()
    p.add_track("audio")
    v = p.add_track("video")
    kinds = [t.kind for t in p.tracks]
    assert kinds == ["video", "overlay", "video", "audio", "audio"]
    assert v.name == "Video 2"
    with pytest.raises(ValueError):
        p.add_track("bogus")


def test_append_and_duration_ignores_longer_audio_unless_audio_only():
    p = Project.new()
    v = p.first_track("video")
    p.append_clip(v, Clip("image", "a.png", duration=2))
    p.append_clip(v, Clip("image", "b.png", duration=3), overlap=0.5)
    assert v.clips[1].start == 1.5
    p.first_track("audio").clips.append(Clip("audio", "m.mp3", duration=60))
    assert p.duration == 4.5
    q = Project.new()
    q.first_track("audio").clips.append(Clip("audio", "m.mp3", duration=7))
    assert q.duration == 7


def test_cues_extend_duration():
    p = Project.new()
    p.cues.append(Cue(1, 9, "x"))
    assert p.duration == 9


def test_trim_left_edge_shifts_in_point_and_stops_at_source_start():
    c = Clip("video", "v.mp4", start=10, duration=5, in_point=1, source_duration=20)
    Project.trim_clip(c, start=11)
    assert (c.start, c.duration, c.in_point) == (11, 4, 2)
    Project.trim_clip(c, start=5)  # would need in_point -4: clamps at source start
    assert (c.start, c.duration, c.in_point) == (9, 6, 0)


def test_trim_right_edge_respects_source_length_but_not_for_images_or_loops():
    c = Clip("video", "v.mp4", start=0, duration=5, in_point=2, source_duration=10)
    Project.trim_clip(c, end=30)
    assert c.duration == 8
    img = Clip("image", "a.png", duration=3)
    Project.trim_clip(img, end=30)
    assert img.duration == 30
    loop = Clip("audio", "m.mp3", duration=3, source_duration=4, loop=True)
    Project.trim_clip(loop, end=30)
    assert loop.duration == 30


def test_trim_never_below_minimum():
    c = Clip("image", "a.png", start=0, duration=3)
    Project.trim_clip(c, end=-5)
    assert c.duration == pytest.approx(0.1)
    Project.trim_clip(c, start=10)
    assert c.duration == pytest.approx(0.1)


def test_split_clip():
    p = Project.new()
    v = p.first_track("video")
    c = Clip("video", "v.mp4", start=2, duration=6, in_point=1, fade_in=1, fade_out=1, source_duration=20)
    v.clips.append(c)
    right = p.split_clip(c, 5)
    assert (c.start, c.duration, c.fade_out, c.fade_in) == (2, 3, 0, 1)
    assert (right.start, right.duration, right.in_point, right.fade_in, right.fade_out) == (5, 3, 4, 0, 1)
    assert v.clips == [c, right]
    assert p.split_clip(c, 2.01) is None  # too close to the edge
    assert p.split_clip(Clip("image"), 1) is None  # not on a track


def test_remove_clip_and_find():
    p = Project.new()
    c = Clip("image", "a.png")
    p.first_track("overlay").clips.append(c)
    assert p.find(c).kind == "overlay"
    p.remove_clip(c)
    assert p.find(c) is None


def test_save_load_roundtrip(tmp_path):
    p = Project.new(width=1080, height=1920, fps=25, background="#112233")
    p.first_track("video").clips.append(Clip("image", "a.png", start=1, duration=2, fade_in=0.5))
    p.first_track("overlay").clips.append(Clip("text", text="Hi", x=0.2, color="#ff0000"))
    p.cues = [Cue(0, 1, "one")]
    p.style.size = 70
    p.style.box = True
    path = tmp_path / "p.lsproj"
    p.save(path)
    q = Project.load(path)
    assert q.to_dict() == p.to_dict()
    assert q.tracks[0].clips[0].fade_in == 0.5 and q.style.box


def test_from_dict_ignores_unknown_keys():
    q = Project.from_dict({"width": 640, "future": 1, "tracks": [{"kind": "video", "x": 1, "clips": [
        {"kind": "image", "path": "a", "newfield": 2}]}], "style": {"size": 10, "zz": 1}})
    assert q.width == 640 and q.tracks[0].clips[0].path == "a" and q.style.size == 10


def test_media_kind():
    assert media_kind("A.JPG") == "image"
    assert media_kind("x.webm") == "video"
    assert media_kind("x.mp3") == "audio"
    assert media_kind("x.txt") is None


# ---- subtitles -----------------------------------------------------------------
SRT = """\ufeff1
00:00:01,000 --> 00:00:02,500
Hello <i>world</i>

2
00:00:03,000 --> 00:00:05,000
Line one
Line two

bad block

3
00:00:06,000 --> 00:00:05,000
ends before it starts
"""


def test_parse_srt():
    cues = parse_srt(SRT)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (1.0, 2.5, "Hello world"), (3.0, 5.0, "Line one\nLine two")]


def test_srt_roundtrip_and_times():
    cues = [Cue(3661.5, 3662.25, "a\nb"), Cue(0, 1, "first")]
    text = write_srt(cues)
    assert text.startswith("1\n00:00:00,000 --> 00:00:01,000\nfirst\n")
    back = parse_srt(text)
    assert [(c.start, c.end, c.text) for c in back] == [(0, 1, "first"), (3661.5, 3662.25, "a\nb")]
    assert parse_srt_time("0:1:2.5") == 62.5
    assert format_srt_time(59.9996) == "00:01:00,000"
    with pytest.raises(ValueError):
        parse_srt_time("nope")


ASS = """[Script Info]
Title: x

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Comment: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,ignored
Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,{\\b1}Bold, with comma\\Nnext
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,first
"""


def test_parse_ass():
    cues = parse_ass(ASS)
    assert [(c.start, c.end, c.text) for c in cues] == [
        (0.0, 1.0, "first"), (1.5, 3.0, "Bold, with comma\nnext")]


def test_load_subtitles_by_extension(tmp_path):
    (tmp_path / "a.srt").write_text(SRT, encoding="utf-8")
    (tmp_path / "b.ass").write_text(ASS, encoding="utf-16")
    assert len(load_subtitles(tmp_path / "a.srt")) == 2
    assert len(load_subtitles(tmp_path / "b.ass")) == 2


def test_ass_color_and_time():
    assert ass_color("#ff8000") == "&H000080FF"
    assert ass_color("#000000", 0.0) == "&HFF000000"
    assert format_ass_time(3725.456) == "1:02:05.46"


def test_build_ass_has_style_cues_and_text_clips():
    p = Project.new(width=1280, height=720)
    p.style.position = "top"
    p.style.box = True
    p.cues = [Cue(1, 2, "Hi {there}\nyou")]
    t = Clip("text", text="TITLE", start=0, duration=3, x=0.5, y=0.25, font_size=80, color="#00ff00",
             fade_in=0.5)
    ass = build_ass(p, text_clips=[t])
    assert "PlayResX: 1280" in ass and "PlayResY: 720" in ass
    default = next(ln for ln in ass.splitlines() if ln.startswith("Style: Default"))
    assert default.split(",")[15] == "3"   # BorderStyle 3 = box
    assert default.split(",")[18] == "8"   # top alignment
    assert "Dialogue: 1,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hi (there)\\Nyou" in ass
    assert "{\\pos(640,180)\\fs80\\1c&H00FF00&\\fad(500,0)}TITLE" in ass
    assert "Hi" not in build_ass(p, include_cues=False)


# ---- auto-edit -------------------------------------------------------------------
def test_natural_sort_and_scan(tmp_path):
    for n in ("img10.png", "img2.png", "img1.jpg", "clip.mp4", "notes.txt", "song.mp3"):
        (tmp_path / n).write_bytes(b"x")
    names = [p.split("\\")[-1].split("/")[-1] for p in scan_folder(tmp_path)]
    assert names == ["clip.mp4", "img1.jpg", "img2.png", "img10.png"]
    assert natural_key("a2") < natural_key("a10")


def test_build_slideshow_crossfades_and_music():
    probe = {"v.mp4": MediaInfo(duration=10, has_audio=True), "m.mp3": MediaInfo(duration=4)}
    opts = SlideshowOptions(image_duration=3, transition=0.5, max_clip=4, music="m.mp3", music_volume=0.5)
    p = build_slideshow(["a.png", "v.mp4", "b.png", "x.txt"], opts, probe=lambda path: probe.get(path))
    clips = p.first_track("video").clips
    assert [(c.kind, c.start, c.duration) for c in clips] == [
        ("image", 0, 3), ("video", 2.5, 4), ("image", 6.0, 3)]
    assert clips[0].fade_in == 0.5 and clips[1].fade_in == 0.5 and clips[2].fade_out == 0.5
    assert clips[1].has_audio and clips[1].source_duration == 10
    music = p.first_track("audio").clips[0]
    assert (music.duration, music.loop, music.volume, music.fade_out) == (9.0, True, 0.5, 2.0)
    assert p.duration == 9.0


def test_build_slideshow_hard_cuts_without_probe():
    p = build_slideshow(["a.png", "b.mp4"], SlideshowOptions(image_duration=2, transition=0))
    clips = p.first_track("video").clips
    assert [(c.start, c.duration, c.fade_in, c.fade_out) for c in clips] == [(0, 2, 0, 0), (2, 2, 0, 0)]
    assert not p.first_track("audio").clips
