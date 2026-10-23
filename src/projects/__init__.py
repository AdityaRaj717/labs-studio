"""Projects (Phase 12): named workspaces, each with its own page settings, prompt
rows, output folder and Google Flow project.

``install()`` (called once from app.py) loads the store, migrates the pre-project
settings into a "Default" project on first start and routes ``pages.*`` settings
to the active project. Without ``install()`` (tests, scripts) nothing changes:
``current()`` is None and ``pages.*`` stay in settings.json.
"""

from __future__ import annotations

from src.projects.store import Project, ProjectBusyError, ProjectStore

_store: ProjectStore | None = None


def install(settings=None, root=None) -> ProjectStore:
    global _store
    from src import config

    settings = settings if settings is not None else config.settings()
    _store = ProjectStore(settings, root=root)
    _store.load()
    settings.pages_backend = _store
    return _store


def uninstall() -> None:
    global _store
    if _store is not None:
        _store.settings.pages_backend = None
    _store = None


def store() -> ProjectStore | None:
    return _store


def current() -> Project | None:
    return _store.active if _store is not None else None


__all__ = ["Project", "ProjectBusyError", "ProjectStore", "current", "install", "store", "uninstall"]
