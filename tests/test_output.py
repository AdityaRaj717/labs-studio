"""Output folder layout and file naming."""

from __future__ import annotations

from datetime import datetime

from src.gen.models import Job, OutputFile
from src.gen.output import output_dir, save_outputs, slugify


def test_output_dir_modes(tmp_path):
    now = datetime(2026, 10, 20, 9, 5, 3)
    assert output_dir(tmp_path, "none") == tmp_path
    assert output_dir(tmp_path, "date", now=now) == tmp_path / "2026-10-20"
    assert output_dir(tmp_path, "batch", now=now) == tmp_path / "20261020-090503"
    assert output_dir(tmp_path, "batch", "B1") == tmp_path / "B1"


def test_slugify():
    assert slugify("A Cat, on: the MAT!") == "a-cat-on-the-mat"
    assert slugify("???") == "prompt"
    assert len(slugify("word " * 30)) <= 40


def test_save_outputs_never_overwrites(tmp_path):
    job = Job("Blue whale", index=7)
    first = save_outputs(job, [OutputFile(b"1"), OutputFile(b"2", ".jpg")], tmp_path)
    assert [p.name for p in first] == ["007_blue-whale_1.png", "007_blue-whale_2.jpg"]
    again = save_outputs(job, [OutputFile(b"3")], tmp_path)
    assert again[0].name == "007_blue-whale_1-1.png"
    assert first[0].read_bytes() == b"1"
