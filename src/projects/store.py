"""Project store: ``<data root>/projects/<id>/project.json`` per project.

A project holds per-page settings (the ``pages.<page>.<key>`` values the config
panels read and write), the prompt rows of each generator page, an output folder
and the Google Flow project (URL and title) the app keeps for it.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.gen.models import Job, JobStatus

log = logging.getLogger(__name__)

DEFAULT_ID = "default"
DEFAULT_NAME = "Default"
OLD_MCP_DIR = r"D:\Tools\google-flow-browser-mcp"  # phase 11a default; its projects file is read once
_MISSING = object()


class ProjectBusyError(RuntimeError):
    """Raised when switching projects while a batch is running."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:30] or "project"


# ---- prompt rows <-> jobs ------------------------------------------------
def job_to_row(job: Job) -> dict[str, Any]:
    return {
        "prompt": job.prompt,
        "refs": [str(p) for p in job.refs],
        "character": job.character,
        "character_refs": [str(p) for p in job.character_refs],
        "status": job.status.value,
        "outputs": [str(p) for p in job.outputs],
        "error": job.error,
    }


def row_to_job(row: dict[str, Any], index: int) -> Job:
    try:
        status = JobStatus(row.get("status", "pending"))
    except ValueError:
        status = JobStatus.PENDING
    if status in (JobStatus.QUEUED, JobStatus.RUNNING):
        status = JobStatus.STOPPED  # the app closed mid-batch
    return Job(
        str(row.get("prompt", "")), index=index,
        refs=[Path(p) for p in row.get("refs", [])],
        status=status,
        progress=1.0 if status is JobStatus.DONE else 0.0,
        outputs=[Path(p) for p in row.get("outputs", [])],
        error=str(row.get("error", "")),
        character=str(row.get("character", "")),
        character_refs=[Path(p) for p in row.get("character_refs", [])],
    )


class Project:
    _save_lock = threading.Lock()  # rows save on the GUI thread, Flow URLs from workers

    def __init__(self, folder: Path, data: dict[str, Any]):
        self.folder = Path(folder)
        self.data = data

    @property
    def file(self) -> Path:
        return self.folder / "project.json"

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def name(self) -> str:
        return self.data.get("name", self.id)

    @property
    def last_used(self) -> str:
        return self.data.get("last_used", "")

    @property
    def output_dir(self) -> Path:
        custom = self.data.get("output_dir") or ""
        return Path(custom) if custom else self.folder / "outputs"

    @property
    def flow_url(self) -> str:
        return (self.data.get("flow") or {}).get("url", "")

    @property
    def flow_title(self) -> str:
        return (self.data.get("flow") or {}).get("title", "")

    def set_flow(self, url: str, title: str = "") -> None:
        self.data["flow"] = {"url": url, "title": title}
        self.save()

    # ---- dotted settings (``pages.<page>.<key>``) -------------------------
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(part, _MISSING)
            if node is _MISSING:
                return default
        return node

    def set(self, path: str, value: Any, save: bool = True) -> None:
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
        if save:
            self.save()

    # ---- prompt rows -------------------------------------------------------
    def rows(self, page_key: str) -> list[dict[str, Any]]:
        return list((self.data.get("rows") or {}).get(page_key, []))

    def set_rows(self, page_key: str, rows: list[dict[str, Any]], save: bool = True) -> None:
        self.data.setdefault("rows", {})[page_key] = rows
        if save:
            self.save()

    def output_count(self) -> int:
        folder = self.output_dir
        if not folder.is_dir():
            return 0
        return sum(1 for p in folder.rglob("*") if p.is_file())

    def save(self) -> None:
        with self._save_lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.file)


class ProjectStore:
    """All projects plus the active one. Also the ``pages.*`` backend for Settings."""

    def __init__(self, settings, root: Path | str | None = None):
        self.settings = settings
        self._root = Path(root) if root else None
        self.projects: dict[str, Project] = {}
        self.active: Project | None = None
        self.listeners: list[Callable[[str, Project], None]] = []
        self.busy_check: Callable[[], bool] | None = None  # set by the main window

    @property
    def root(self) -> Path:
        if self._root is not None:
            return self._root
        custom = self.settings.get("projects.data_root", "")
        if custom:
            return Path(custom)
        from src.config import app_data_dir

        return app_data_dir()

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    # ---- loading -------------------------------------------------------------
    def load(self) -> None:
        self.projects.clear()
        if self.projects_dir.is_dir():
            for f in sorted(self.projects_dir.glob("*/project.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    log.warning("Skipping unreadable project %s (%s)", f, exc)
                    continue
                if isinstance(data, dict) and data.get("id"):
                    self.projects[data["id"]] = Project(f.parent, data)
        if not self.projects:
            self._migrate()
        active_id = self.settings.get("projects.active", "")
        self.active = self.projects.get(active_id) or self.list()[0]
        if self.active.id != active_id:
            self.settings.set("projects.active", self.active.id)
        log.info("Projects: %d, active %s (%s)", len(self.projects), self.active.name, self.projects_dir)

    def _migrate(self) -> None:
        """First start with projects: today's page settings and outputs become "Default"."""
        from src.config import app_data_dir

        pages = copy.deepcopy(self.settings.data.get("pages", {}))
        project = self._new(DEFAULT_ID, DEFAULT_NAME, pages=pages)
        old_outputs = app_data_dir() / "outputs"
        project.data["output_dir"] = str(old_outputs)  # existing files stay where they are
        url = self._old_flow_url()
        if url:
            project.data["flow"] = {"url": url, "title": ""}
        project.save()
        self.projects[project.id] = project
        log.info("Migrated settings into project %r (outputs %s)", project.name, old_outputs)

    def _old_flow_url(self) -> str:
        """The Flow project the phase 11a MCP kept for the app's campaign, if any."""
        campaign = self.settings.get("web.flow_campaign", "labs-studio")
        f = Path(self.settings.get("web.flow_mcp_dir", "") or OLD_MCP_DIR) / "config" / "flow.projects.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        for p in data.get("projects", []):
            if (p.get("campaign") or "").lower() == campaign.lower():
                return p.get("url", "")
        return ""

    def _new(self, pid: str, name: str, pages: dict | None = None) -> Project:
        now = _now()
        data = {"id": pid, "name": name, "created": now, "last_used": now, "output_dir": "",
                "pages": pages or {}, "rows": {}, "flow": {"url": "", "title": ""}}
        return Project(self.projects_dir / pid, data)

    # ---- queries ---------------------------------------------------------------
    def list(self) -> list[Project]:
        return sorted(self.projects.values(), key=lambda p: p.last_used, reverse=True)

    def find(self, key: str) -> Project | None:
        """By id, else by name (case-insensitive)."""
        if key in self.projects:
            return self.projects[key]
        low = key.strip().lower()
        return next((p for p in self.projects.values() if p.name.lower() == low), None)

    def _check_name(self, name: str, exclude: str = "") -> str:
        name = name.strip()
        if not name:
            raise ValueError("A project needs a name.")
        clash = self.find(name)
        if clash is not None and clash.id != exclude and clash.name.lower() == name.lower():
            raise ValueError(f"A project named {name!r} already exists.")
        return name

    # ---- changes ---------------------------------------------------------------
    def create(self, name: str, settings_from: str | None = None) -> Project:
        name = self._check_name(name)
        pid = _slug(name)
        while pid in self.projects or (self.projects_dir / pid).exists():
            pid = f"{_slug(name)}-{secrets.token_hex(2)}"
        pages = copy.deepcopy(self.projects[settings_from].data.get("pages", {})) if settings_from else {}
        project = self._new(pid, name, pages=pages)
        project.save()
        self.projects[pid] = project
        self._emit("created", project)
        return project

    def rename(self, pid: str, name: str) -> Project:
        project = self.projects[pid]
        project.data["name"] = self._check_name(name, exclude=pid)
        project.save()
        self._emit("renamed", project)
        return project

    def set_output_dir(self, pid: str, folder: str) -> None:
        project = self.projects[pid]
        project.data["output_dir"] = folder
        project.save()
        self._emit("changed", project)

    def delete(self, pid: str, delete_files: bool = False) -> None:
        """Forget a project. Its folder (and outputs inside it) is removed only if asked."""
        if len(self.projects) <= 1:
            raise ValueError("The last project can't be deleted.")
        project = self.projects[pid]
        if self.active is project:
            self.activate(next(p.id for p in self.list() if p.id != pid))
        del self.projects[pid]
        if delete_files:
            shutil.rmtree(project.folder, ignore_errors=True)
        elif project.file.exists():
            os.replace(project.file, project.folder / "project.deleted.json")
        self._emit("deleted", project)

    def activate(self, pid: str) -> Project:
        project = self.projects[pid]
        if project is self.active:
            return project
        if self.busy_check is not None and self.busy_check():
            raise ProjectBusyError("A batch is running. Stop it before switching projects.")
        self.active = project
        project.data["last_used"] = _now()
        project.save()
        self.settings.set("projects.active", pid)
        log.info("Project: %s", project.name)
        self._emit("switched", project)
        return project

    def _emit(self, event: str, project: Project) -> None:
        for fn in list(self.listeners):
            try:
                fn(event, project)
            except Exception:  # noqa: BLE001 - one bad listener must not break the rest
                log.exception("Project listener failed on %s", event)

    # ---- Settings backend for ``pages.*`` --------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        return self.active.get(path, default) if self.active else default

    def set(self, path: str, value: Any, save: bool = True) -> None:
        if self.active is not None:
            self.active.set(path, value, save=save)
