"""Attach characters and scenes to generator jobs so their reference images reach the provider.

A job keeps its own refs (from the ref folder) in ``job.refs``. Attaching a
character puts the character's images first in ``job.refs`` and remembers which
paths came from it in ``job.character_refs``, so detaching or re-syncing removes
exactly those and leaves the row's own refs alone.

Phase 14b: a row can name more characters (``job.cast``, e.g. two people in one
shot) and scenes, i.e. reusable places (``job.scenes``, refs in ``job.scene_refs``).
``job.character`` stays the first character. The Google Flow provider passes them
all by name to Flow's Characters section instead of uploading their images.
"""

from __future__ import annotations

import re

from src.characters.store import CharacterStore
from src.gen.models import Job


def _strip(job: Job) -> None:
    own = set(job.character_refs)
    job.refs = [r for r in job.refs if r not in own]
    job.character_refs = []


def _strip_scenes(job: Job) -> None:
    own = set(job.scene_refs)
    job.refs = [r for r in job.refs if r not in own]
    job.scene_refs = []


def character_ids(job: Job) -> list[str]:
    """Every character on the row, the first one first."""
    return [c for c in dict.fromkeys([job.character, *job.cast]) if c]


def _apply_characters(job: Job, ids: list[str], store: CharacterStore) -> int:
    _strip(job)
    ids = [c for c in dict.fromkeys(ids) if c and store.get(c)]
    job.character = ids[0] if ids else ""
    job.cast = ids[1:]
    refs: list = []
    for char_id in ids:
        refs += [p for p in store.ref_paths(char_id) if p not in job.refs and p not in refs]
    job.character_refs = refs
    job.refs = refs + job.refs
    return len(refs)


def attach(job: Job, char_id: str, store: CharacterStore) -> int:
    """Attach (or replace) the job's character. Returns the number of refs it brought."""
    if not store.get(char_id):
        _apply_characters(job, [], store)
        return 0
    return _apply_characters(job, [char_id] + [c for c in job.cast if c != char_id], store)


def set_characters(job: Job, ids: list[str], store: CharacterStore) -> int:
    """Put exactly these characters on the row (first = ``job.character``)."""
    return _apply_characters(job, ids, store)


def detach(job: Job) -> None:
    _strip(job)
    job.character = ""
    job.cast = []


def set_scenes(job: Job, ids: list[str], scenes: CharacterStore) -> int:
    """Put exactly these scenes on the row; their images go after the characters'."""
    _strip_scenes(job)
    ids = [s for s in dict.fromkeys(ids) if s and scenes.get(s)]
    job.scenes = ids
    refs: list = []
    for scene_id in ids:
        refs += [p for p in scenes.ref_paths(scene_id) if p not in job.refs and p not in refs]
    job.scene_refs = refs
    n = len(job.character_refs)
    job.refs = job.refs[:n] + refs + job.refs[n:]
    return len(refs)


def sync(job: Job, store: CharacterStore, scenes: CharacterStore | None = None) -> None:
    """Re-read the characters' (and scenes') current images; they may have changed."""
    if job.character or job.cast:
        _apply_characters(job, character_ids(job), store)
    elif job.character_refs:
        _strip(job)
    if scenes is not None and (job.scenes or job.scene_refs):
        set_scenes(job, job.scenes, scenes)


def mentions(prompt: str, name: str) -> bool:
    name = name.strip().lower()
    return bool(name) and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", prompt.lower()) is not None


def named_in(prompt: str, store: CharacterStore) -> list[str]:
    """Ids of the entries the prompt names, in prompt order. Longer names win, so
    "Captain Mia" is found once and does not also count as "Mia"."""
    text = prompt.lower()
    found: list[tuple[int, str]] = []
    for char in sorted(store.all(), key=lambda c: len(c.name), reverse=True):
        name = char.name.strip().lower()
        if not name:
            continue
        m = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)
        if m:
            found.append((m.start(), char.id))
            text = text[:m.start()] + " " * len(name) + text[m.end():]
    return [cid for _, cid in sorted(found)]


def match_by_name(jobs: list[Job], store: CharacterStore, scenes: CharacterStore | None = None) -> int:
    """Attach the characters (and scenes) every row's prompt names. Returns rows changed.

    A row that already has characters keeps them; a row without gets every one it names.
    """
    changed = 0
    for job in jobs:
        before = (character_ids(job), list(job.scenes))
        named = [] if job.character else named_in(job.prompt, store)
        if named:
            _apply_characters(job, named, store)
        if scenes is not None:
            places = named_in(job.prompt, scenes)
            if places:
                set_scenes(job, list(dict.fromkeys(job.scenes + places)), scenes)
        if (character_ids(job), list(job.scenes)) != before:
            changed += 1
    return changed


def character_label(job: Job, store: CharacterStore | None) -> str:
    if store is None:
        return ""
    names = [c.name for c in (store.get(i) for i in character_ids(job)) if c]
    return ", ".join(names)


def scene_label(job: Job, scenes: CharacterStore | None) -> str:
    if scenes is None:
        return ""
    return ", ".join(s.name for s in (scenes.get(i) for i in job.scenes) if s)
