"""JSON settings store with dotted-key get/set.

Settings live in ``<AppData>/LabsStudio/settings.json``. Values are saved on
every ``set`` (the file is tiny), so nothing is lost if the app crashes.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_DIR_NAME = "LabsStudio"

DEFAULTS: dict[str, Any] = {
    "language": "en",
    "theme": "dark",
    "sidebar_collapsed": False,
    "window": {"geometry": None},
    # Phase 11: web-session providers (real Chrome over CDP, profile kept off C:).
    "web": {
        "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "profile_dir": r"D:\glabs_web\chrome-profile",
        "diag_dir": r"D:\glabs_web\diag",
        "port": 9333,
        "gap_min": 20.0,
        "gap_max": 45.0,
        "caps": {"flow": 60},
        "usage": {},
    },
}

_MISSING = object()


def app_data_dir() -> Path:
    """Return ``%APPDATA%\\LabsStudio`` (created if needed).

    When a QCoreApplication named ``LabsStudio`` exists (set up in app.py with
    no organisation name), QStandardPaths.AppDataLocation resolves to exactly
    this folder. Without one (tests, scripts) we build the same path from APPDATA.
    """
    path: Path | None = None
    try:
        from PySide6.QtCore import QCoreApplication, QStandardPaths

        if QCoreApplication.instance() and QCoreApplication.applicationName() == APP_DIR_NAME:
            loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            path = Path(loc) if loc else None
    except ImportError:
        pass
    if path is None:
        appdata = os.environ.get("APPDATA")
        path = (Path(appdata) if appdata else Path.home() / ".config") / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    """Dict-backed settings with dotted paths, e.g. ``get("window.geometry")``."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else app_data_dir() / "settings.json"
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Could not read settings %s (%s); using defaults", self.path, exc)
            return
        if isinstance(loaded, dict):
            self.data = _deep_merge(DEFAULTS, loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

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


_settings: Settings | None = None


def settings() -> Settings:
    """Process-wide settings instance (created on first use)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get(path: str, default: Any = None) -> Any:
    return settings().get(path, default)


def set(path: str, value: Any, save: bool = True) -> None:  # noqa: A001 - mirrors spec API
    settings().set(path, value, save=save)
