"""Reference-image auto-match by filename keyword."""

from __future__ import annotations

from src.gen.models import Job
from src.gen.refmatch import list_ref_images, match_refs


def test_match_by_keyword_and_index(tmp_path):
    for name in ("red_car.png", "Owl.JPG", "2.webp", "car.txt", "cart.png"):
        (tmp_path / name).write_bytes(b"x")
    jobs = [
        Job("A RED car on a road", index=1),
        Job("an owl at night", index=2),
        Job("cartoon dog", index=3),
    ]
    assert len(list_ref_images(tmp_path)) == 4  # .txt ignored

    added = match_refs(jobs, tmp_path)
    names = [[p.name for p in j.refs] for j in jobs]
    assert names == [["red_car.png"], ["2.webp", "Owl.JPG"], []]
    assert added == 3
    # Running again does not duplicate.
    assert match_refs(jobs, tmp_path) == 0


def test_missing_folder(tmp_path):
    assert match_refs([Job("x", index=1)], tmp_path / "nope") == 0
