"""Prompt import from text, .txt and .xlsx."""

from __future__ import annotations

from openpyxl import Workbook

from src.gen.importer import load_prompts, load_txt, load_xlsx, parse_text


def test_lines_mode_skips_blank_and_strips():
    assert parse_text("  a cat \n\n\nb dog\r\n", "lines") == ["a cat", "b dog"]


def test_blocks_mode_folds_newlines():
    text = "a red\ncar\n\n  \nblue sky\n"
    assert parse_text(text, "blocks") == ["a red car", "blue sky"]


def test_auto_picks_mode():
    assert parse_text("one\ntwo") == ["one", "two"]
    assert parse_text("one\ncont\n\ntwo") == ["one cont", "two"]


def test_load_txt_with_bom(tmp_path):
    path = tmp_path / "p.txt"
    path.write_bytes("\ufefffirst\nsecond\n".encode("utf-8"))
    assert load_txt(path) == ["first", "second"]


def test_load_xlsx_header_and_plain(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "Prompt"])
    ws.append([1, "a fox"])
    ws.append([2, None])
    ws.append([3, "  an owl "])
    with_header = tmp_path / "h.xlsx"
    wb.save(with_header)
    assert load_xlsx(with_header) == ["a fox", "an owl"]

    wb = Workbook()
    wb.active.append(["just a prompt"])
    wb.active.append(["another"])
    plain = tmp_path / "plain.xlsx"
    wb.save(plain)
    assert load_prompts(plain) == ["just a prompt", "another"]
