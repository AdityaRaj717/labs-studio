"""Prompt import: pasted text, .txt files and .xlsx sheets."""

from __future__ import annotations

import re
from pathlib import Path

MODES = ("auto", "lines", "blocks")
_BLANK_LINE = re.compile(r"\n\s*\n")


def parse_text(text: str, mode: str = "auto") -> list[str]:
    """Split text into prompts.

    ``lines``: one prompt per non-empty line. ``blocks``: prompts separated by
    blank lines, inner newlines folded to spaces. ``auto``: blocks if the text
    has a blank line, else lines.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    if mode == "auto":
        mode = "blocks" if _BLANK_LINE.search(text.strip()) else "lines"
    if mode == "blocks":
        parts = [" ".join(line.strip() for line in block.splitlines() if line.strip())
                 for block in _BLANK_LINE.split(text)]
    elif mode == "lines":
        parts = [line.strip() for line in text.split("\n")]
    else:
        raise ValueError(f"Unknown import mode {mode!r}")
    return [p for p in parts if p]


def load_txt(path: Path | str, mode: str = "auto") -> list[str]:
    return parse_text(Path(path).read_text(encoding="utf-8-sig", errors="replace"), mode)


def load_xlsx(path: Path | str) -> list[str]:
    """Prompts from the first sheet: the column headed "prompt", else column A."""
    from openpyxl import load_workbook

    wb = load_workbook(Path(path), read_only=True, data_only=True)
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return []
    col, start = 0, 0
    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    if "prompt" in header:
        col, start = header.index("prompt"), 1
    prompts = []
    for row in rows[start:]:
        if col < len(row) and row[col] is not None:
            value = str(row[col]).strip()
            if value:
                prompts.append(value)
    return prompts


def load_prompts(path: Path | str, mode: str = "auto") -> list[str]:
    suffix = Path(path).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return load_xlsx(path)
    if suffix in (".txt", ".text", ".csv", ""):
        return load_txt(path, mode)
    raise ValueError(f"Unsupported prompt file: {Path(path).name}")
