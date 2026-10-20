"""Attach characters to generator jobs so their reference images reach the provider.

A job keeps its own refs (from the ref folder) in ``job.refs``. Attaching a
character puts the character's images first in ``job.refs`` and remembers which
paths came from it in ``job.character_refs``, so detaching or re-syncing removes
exactly those and leaves the row's own refs alone.
"""

from __future__ import annotations

import re

from src.characters.store import CharacterStore
from src.gen.models import Job


def _strip(job: Job) -> None:
    own = set(job.character_refs)
    job.refs = [r for r in job.refs if r not in own]
    job.character_refs = []


def attach(job: Job, char_id: str, store: CharacterStore) -> int:
    """Attach (or replace) the job's character. Returns the number of refs it brought."""
    _strip(job)
    char = store.get(char_id)
    if not char:
        job.character = ""
        return 0
    job.character = char_id
    refs = [p for p in store.ref_paths(char_id) if p not in job.refs]
    job.character_refs = refs
    job.refs = refs + job.refs
    return len(refs)


def detach(job: Job) -> None:
    _strip(job)
    job.character = ""


def sync(job: Job, store: CharacterStore) -> None:
    """Re-read the character's current images (they may have changed since attaching)."""
    if job.character:
        attach(job, job.character, store)
    elif job.character_refs:
        _strip(job)


def mentions(prompt: str, name: str) -> bool:
    name = name.strip().lower()
    return bool(name) and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", prompt.lower()) is not None


def match_by_name(jobs: list[Job], store: CharacterStore) -> int:
    """Attach a character to every job without one whose prompt names it. Returns rows changed.

    Longer names win, so "Captain Mia" beats "Mia" when both exist.
    """
    chars = sorted(store.all(), key=lambda c: len(c.name), reverse=True)
    changed = 0
    for job in jobs:
        if job.character:
            continue
        for char in chars:
            if mentions(job.prompt, char.name):
                attach(job, char.id, store)
                changed += 1
                break
    return changed


def character_label(job: Job, store: CharacterStore | None) -> str:
    if not job.character or store is None:
        return ""
    char = store.get(job.character)
    return char.name if char else ""
