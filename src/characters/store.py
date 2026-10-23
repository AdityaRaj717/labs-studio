"""CharacterStore: characters saved as JSON with their reference images copied alongside.

Layout under ``<AppData>/LabsStudio/characters/``::

    characters.json          {"version": 1, "characters": [{id, name, notes, voice, refs, flow}]}
    <id>/<image files>       copies of the reference images (refs holds the file names)

Scenes (Phase 14b: reusable places) use the same store under ``scenes/`` with
``scenes.json``. Both libraries are global, not per project. ``flow`` maps a Flow
project URL to the entry's name in that project's Characters section, so the app
knows where it is already set up (``src.characters.flow_sync``).

The store is Qt-free. Every change is written straight away (the file is tiny).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.gen.refmatch import IMAGE_EXTS

log = logging.getLogger(__name__)

INDEX_FILE = "characters.json"
INDEX_FILES = {"character": "characters.json", "scene": "scenes.json"}
VERSION = 1


@dataclass
class Character:
    name: str
    notes: str = ""
    voice: str = ""
    refs: list[str] = field(default_factory=list)  # file names inside the character's folder
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    flow: dict[str, str] = field(default_factory=dict)  # Flow project URL -> name there (14b)

    @classmethod
    def from_dict(cls, d: dict) -> "Character":
        return cls(
            name=str(d.get("name") or "").strip() or "Unnamed",
            notes=str(d.get("notes") or ""),
            voice=str(d.get("voice") or ""),
            refs=[str(r) for r in d.get("refs") or [] if isinstance(r, str)],
            id=str(d.get("id") or uuid.uuid4().hex[:12]),
            flow={str(k): str(v) for k, v in (d.get("flow") or {}).items() if k and v}
            if isinstance(d.get("flow"), dict) else {},
        )


class CharacterStore:
    def __init__(self, root: Path | str, kind: str = "character"):
        self.root = Path(root)
        self.kind = kind  # "character" or "scene" (a place)
        self._chars: list[Character] = []
        self._listeners: list = []
        self._lock = threading.RLock()  # Flow sync records names from worker threads
        self.load()

    # ---- persistence -------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.root / INDEX_FILES.get(self.kind, INDEX_FILE)

    def load(self) -> None:
        self._chars = []
        if not self.index_path.is_file():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("Could not read %s: %s", self.index_path, exc)
            return
        for d in data.get("characters") or []:
            if isinstance(d, dict):
                self._chars.append(Character.from_dict(d))

    def save(self) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            data = {"version": VERSION, "characters": [asdict(c) for c in self._chars]}
            tmp = self.index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.index_path)
        for listener in list(self._listeners):
            listener()

    def subscribe(self, callback) -> None:
        """Call ``callback()`` after every saved change (pages refresh their menus)."""
        self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    # ---- queries -----------------------------------------------------
    def all(self) -> list[Character]:
        return list(self._chars)

    def get(self, char_id: str) -> Character | None:
        return next((c for c in self._chars if c.id == char_id), None)

    def by_name(self, name: str) -> Character | None:
        key = name.strip().lower()
        return next((c for c in self._chars if c.name.lower() == key), None)

    def folder(self, char_id: str) -> Path:
        return self.root / char_id

    def ref_paths(self, char_id: str) -> list[Path]:
        """Absolute paths of a character's reference images that still exist on disk."""
        char = self.get(char_id)
        if not char:
            return []
        folder = self.folder(char_id)
        return [folder / r for r in char.refs if (folder / r).is_file()]

    # ---- changes -----------------------------------------------------
    def add(self, name: str, notes: str = "", voice: str = "",
            images: list[Path | str] | None = None) -> Character:
        char = Character(name=name.strip() or "Unnamed", notes=notes, voice=voice)
        self._chars.append(char)
        for image in images or []:
            self._copy_ref(char, Path(image))
        self.save()
        return char

    def update(self, char_id: str, *, name: str | None = None, notes: str | None = None,
               voice: str | None = None) -> Character:
        char = self._require(char_id)
        if name is not None and name.strip():
            char.name = name.strip()
        if notes is not None:
            char.notes = notes
        if voice is not None:
            char.voice = voice
        self.save()
        return char

    def delete(self, char_id: str) -> bool:
        char = self.get(char_id)
        if not char:
            return False
        self._chars.remove(char)
        self.save()
        shutil.rmtree(self.folder(char_id), ignore_errors=True)
        return True

    def add_refs(self, char_id: str, images: list[Path | str]) -> list[str]:
        """Copy images into the character's folder. Returns the stored file names."""
        char = self._require(char_id)
        added = [n for n in (self._copy_ref(char, Path(p)) for p in images) if n]
        self.save()
        return added

    def remove_ref(self, char_id: str, filename: str) -> bool:
        char = self._require(char_id)
        if filename not in char.refs:
            return False
        char.refs.remove(filename)
        self.save()
        try:
            (self.folder(char_id) / filename).unlink()
        except OSError:
            pass
        return True

    # ---- Flow (Phase 14b) ----------------------------------------------
    def set_flow(self, char_id: str, project_url: str, name: str) -> None:
        """Record that the entry exists as ``name`` in the Flow project ``project_url``."""
        with self._lock:
            char = self._require(char_id)
            if char.flow.get(project_url) == name:
                return
            char.flow[project_url] = name
            self.save()

    def drop_flow(self, char_id: str, project_url: str) -> bool:
        """Forget the entry's Flow copy in ``project_url`` (it was deleted there)."""
        with self._lock:
            char = self.get(char_id)
            if not char or project_url not in char.flow:
                return False
            del char.flow[project_url]
            self.save()
            return True

    def _require(self, char_id: str) -> Character:
        char = self.get(char_id)
        if not char:
            raise KeyError(f"No character {char_id!r}")
        return char

    def _copy_ref(self, char: Character, src: Path) -> str:
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXTS:
            log.warning("Skipped reference %s (not an image file)", src)
            return ""
        folder = self.folder(char.id)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / src.name
        n = 2
        while dest.exists():
            dest = folder / f"{src.stem}_{n}{src.suffix}"
            n += 1
        shutil.copy2(src, dest)
        char.refs.append(dest.name)
        return dest.name


_default: CharacterStore | None = None
_scenes: CharacterStore | None = None


def default_store() -> CharacterStore:
    """The app-wide store under the app-data dir (created on first use)."""
    global _default
    if _default is None:
        from src.config import app_data_dir

        _default = CharacterStore(app_data_dir() / "characters")
    return _default


def scene_store() -> CharacterStore:
    """The app-wide scene (place) library, next to the characters."""
    global _scenes
    if _scenes is None:
        from src.config import app_data_dir

        _scenes = CharacterStore(app_data_dir() / "scenes", kind="scene")
    return _scenes
