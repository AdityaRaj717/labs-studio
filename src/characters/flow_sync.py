"""Make sure library characters and scenes exist in a Google Flow project (Phase 14b).

Flow keeps characters per project and cannot paste them across projects. Each
library entry remembers where it already exists (``entry.flow``: Flow project
URL -> name there). ``FlowSync.ensure`` returns the entry's Flow name in a
project, and sets it up first when needed:

1. already recorded for that project: use the name;
2. recorded in another project: ``flow_import_character`` copies it (the MCP
   downloads the portrait at full size and creates it again, free);
3. otherwise ``flow_create_character`` / ``flow_create_scene`` from the entry's
   first image (free), or, without images, from its notes as a description
   (Flow generates a portrait: an image generation).

Scenes are places: in Flow they are characters marked as a place, because Flow's
own Scenes are video timelines. ``verify`` lists the project's characters once per
session and forgets recorded names that were deleted in Flow.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from src.characters.store import Character, CharacterStore
from src.web.mcp_client import McpToolError

log = logging.getLogger(__name__)

CREATE_TIMEOUT = 360  # upload + processing is 10-30 s; a generated portrait takes minutes
LIST_TIMEOUT = 120

Call = Callable[[str, dict, float], dict]  # (tool, args, timeout) -> result


class SyncError(RuntimeError):
    """An entry could not be set up in Flow (no image and no description, or the MCP failed)."""


class FlowSync:
    def __init__(self, call: Call, characters: CharacterStore, scenes: CharacterStore):
        self.call = call
        self.stores = {"character": characters, "scene": scenes}
        self._verified: set[str] = set()
        self._lock = threading.Lock()  # one Flow page: sync one entry at a time

    def store(self, kind: str) -> CharacterStore:
        return self.stores[kind]

    # ---- one entry ----------------------------------------------------
    def ensure(self, kind: str, entry_id: str, project_url: str) -> str:
        """Return the entry's name in the Flow project, creating or importing it first."""
        store = self.store(kind)
        with self._lock:
            entry = store.get(entry_id)
            if entry is None:
                raise SyncError(f"no {kind} with id {entry_id!r} in the library")
            name = entry.flow.get(project_url)
            if name:
                return name
            res = self._import(entry, project_url) or self._create(kind, entry, project_url)
            name = str(res.get("name") or entry.name)
            store.set_flow(entry.id, project_url, name)
            log.info("Flow %s %r ready in %s (%s)", kind, name, project_url,
                     "imported" if res.get("imported_from") else
                     "created" if res.get("created", True) else "already there")
            return name

    def _import(self, entry: Character, project_url: str) -> dict | None:
        for source, name in entry.flow.items():
            if source == project_url:
                continue
            try:
                return self.call("flow_import_character",
                                 {"project_url": project_url, "from_project_url": source, "name": name},
                                 CREATE_TIMEOUT)
            except McpToolError as exc:
                log.warning("Could not import %r from %s (%s); creating it instead", name, source, exc)
        return None

    def _create(self, kind: str, entry: Character, project_url: str) -> dict:
        store = self.store(kind)
        args: dict = {"project_url": project_url, "name": entry.name}
        if entry.notes.strip():
            args["info"] = entry.notes.strip()
        images = store.ref_paths(entry.id)
        if images:
            args["images"] = [str(images[0].resolve())]
        elif entry.notes.strip():
            args["prompt"] = entry.notes.strip()
            args["auto_confirm"] = True  # an image generation (free on this account), no video
        else:
            raise SyncError(f"{entry.name!r} has no image and no description to create it in Flow from")
        tool = "flow_create_scene" if kind == "scene" else "flow_create_character"
        res = self.call(tool, args, CREATE_TIMEOUT)
        if res.get("status") != "success":
            raise SyncError(f"{tool} for {entry.name!r} returned {res.get('status')!r}: {res.get('message', '')}")
        return res

    # ---- a whole project ------------------------------------------------
    def verify(self, project_url: str, force: bool = False) -> int:
        """Forget recorded names that no longer exist in the Flow project. Returns how many."""
        if not force and project_url in self._verified:
            return 0
        with self._lock:
            res = self.call("flow_list_characters", {"project_url": project_url}, LIST_TIMEOUT)
            present = {str(c.get("name", "")) for c in res.get("characters") or []}
            dropped = 0
            for kind, store in self.stores.items():
                for entry in store.all():
                    name = entry.flow.get(project_url)
                    if name and name not in present:
                        store.drop_flow(entry.id, project_url)
                        dropped += 1
                        log.info("Flow %s %r is gone from %s; it will be set up again", kind, name, project_url)
            self._verified.add(project_url)
            return dropped

    def sync(self, project_url: str, character_ids: list[str], scene_ids: list[str],
             verify: bool = True) -> dict:
        """Set up every listed entry in the project. Errors are collected, not raised."""
        if verify:
            try:
                self.verify(project_url)
            except McpToolError as exc:
                log.warning("Could not list the Flow characters of %s: %s", project_url, exc)
        out: dict = {"characters": {}, "scenes": {}, "errors": []}
        for kind, ids, key in (("character", character_ids, "characters"), ("scene", scene_ids, "scenes")):
            for entry_id in dict.fromkeys(ids):
                try:
                    out[key][entry_id] = self.ensure(kind, entry_id, project_url)
                except (SyncError, McpToolError) as exc:
                    out["errors"].append(str(exc))
                    log.warning("Flow sync: %s", exc)
        return out

    def names(self, project_url: str, character_ids: list[str], scene_ids: list[str]) -> tuple[list[str], list[str]]:
        """Flow names for a job, setting up what is missing. Raises on the first failure."""
        try:
            self.verify(project_url)  # once per session: catches entries deleted in Flow
        except McpToolError as exc:
            log.warning("Could not list the Flow characters of %s: %s", project_url, exc)
        chars = [self.ensure("character", c, project_url) for c in dict.fromkeys(character_ids)]
        scenes = [self.ensure("scene", s, project_url) for s in dict.fromkeys(scene_ids)]
        return chars, scenes


def used_in_rows(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Character and scene ids attached to saved prompt rows (``project.json`` rows)."""
    chars: list[str] = []
    scenes: list[str] = []
    for row in rows:
        chars += [str(row.get("character") or "")] + [str(c) for c in row.get("cast") or []]
        scenes += [str(s) for s in row.get("scenes") or []]
    return [c for c in dict.fromkeys(chars) if c], [s for s in dict.fromkeys(scenes) if s]
