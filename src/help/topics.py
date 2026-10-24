"""Help topics (Phase 15): Markdown files in ``help/<lang>/``, ordered by that folder's README.

Qt-free so the tests and the screenshot tool can use it. A topic's id is its file
stem and its title is the first ``# `` heading. Links between topics are relative
``.md`` links, so the same files read fine on GitHub.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LANGUAGE = "en"
INDEX_FILE = "README.md"

_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


@dataclass
class Topic:
    id: str
    title: str
    path: Path
    text: str

    @property
    def folder(self) -> Path:
        return self.path.parent


def help_dir() -> Path:
    """``help/`` next to the source tree, or next to the executable / in the bundle when frozen."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "help")
        candidates.append(Path(sys.executable).parent / "help")
    candidates.append(Path(__file__).resolve().parents[2] / "help")
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[-1]


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def topic_order(folder: Path) -> list[str]:
    """Topic ids in the order the folder's README links them."""
    index = folder / INDEX_FILE
    if not index.is_file():
        return sorted(p.stem for p in folder.glob("*.md") if p.name != INDEX_FILE)
    order: list[str] = []
    for is_img, _label, target in _LINK.findall(index.read_text(encoding="utf-8")):
        name = target.split("#", 1)[0]
        if is_img or not name.endswith(".md") or "/" in name or name == INDEX_FILE:
            continue
        stem = name[:-3]
        if stem not in order:
            order.append(stem)
    return order


def load_topics(lang: str = DEFAULT_LANGUAGE, root: Path | None = None) -> list[Topic]:
    """Topics of ``lang`` in README order; files missing in ``lang`` come from English."""
    root = root or help_dir()
    base = root / DEFAULT_LANGUAGE
    folder = root / lang if (root / lang).is_dir() else base
    topics: list[Topic] = []
    for tid in topic_order(base if base.is_dir() else folder):
        path = folder / f"{tid}.md"
        if not path.is_file():
            path = base / f"{tid}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        topics.append(Topic(tid, _title(text, tid), path, text))
    return topics


def search(topics: list[Topic], query: str) -> list[Topic]:
    """Topics containing every word of ``query`` (title or text), most hits first; title hits count double."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return list(topics)
    scored: list[tuple[int, int, Topic]] = []
    for i, t in enumerate(topics):
        title, text = t.title.lower(), t.text.lower()
        if not all(w in text or w in title for w in words):
            continue
        score = sum(text.count(w) + 2 * title.count(w) for w in words)
        scored.append((-score, i, t))
    return [t for _, _, t in sorted(scored)]


def links(topic: Topic) -> list[str]:
    """Link targets (not images) in the topic."""
    return [target for is_img, _l, target in _LINK.findall(topic.text) if not is_img]


def images(topic: Topic) -> list[str]:
    return [target for is_img, _l, target in _LINK.findall(topic.text) if is_img]


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I))


def resolve_link(topic: Topic, target: str) -> tuple[str | None, str]:
    """Map a relative link to ``(topic id, fragment)``; ``(None, "")`` for anything else."""
    if is_external(target):
        return None, ""
    name, _, fragment = target.partition("#")
    if not name:
        return topic.id, fragment
    if not name.endswith(".md") or "/" in name:
        return None, ""
    return name[:-3], fragment
