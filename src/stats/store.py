"""Run statistics: jobs, successes, failures and saved outputs per provider.

Qt-free and thread-safe: ``record`` is called from queue worker threads via
``JobQueue``'s finish hook. Counts persist to ``stats.json`` in app data.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable

from src.gen.models import Job, JobStatus

log = logging.getLogger(__name__)

FIELDS = ("jobs", "done", "failed", "stopped", "outputs")


def _empty() -> dict[str, int]:
    return {f: 0 for f in FIELDS}


class StatsStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._data: dict[str, dict] = {}  # provider key -> {"name": str, **FIELDS}
        self._since = ""
        self._listeners: list[Callable[[], None]] = []
        self.load()

    # ---- persistence -------------------------------------------------
    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s: %s", self.path, exc)
            return
        with self._lock:
            self._since = str(raw.get("since", ""))
            for key, row in (raw.get("providers") or {}).items():
                clean = _empty()
                clean.update({f: int(row.get(f, 0)) for f in FIELDS})
                clean["name"] = str(row.get("name", key))
                self._data[key] = clean

    def save(self) -> None:
        if not self.path:
            return
        with self._lock:
            payload = {"since": self._since, "providers": self._data}
            text = json.dumps(payload, indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Could not save %s: %s", self.path, exc)

    # ---- counting ----------------------------------------------------
    def record(self, provider_key: str, provider_name: str, status: JobStatus, outputs: int = 0) -> None:
        with self._lock:
            if not self._since:
                from datetime import datetime
                self._since = datetime.now().isoformat(timespec="seconds")
            row = self._data.setdefault(provider_key, {**_empty(), "name": provider_name})
            row["name"] = provider_name or row.get("name", provider_key)
            row["jobs"] += 1
            if status is JobStatus.DONE:
                row["done"] += 1
                row["outputs"] += int(outputs)
            elif status is JobStatus.FAILED:
                row["failed"] += 1
            elif status is JobStatus.STOPPED:
                row["stopped"] += 1
        self.save()
        self._notify()

    def on_job_finished(self, provider, job: Job) -> None:
        """``JobQueue`` finish hook."""
        self.record(getattr(provider, "key", "?"), getattr(provider, "name", ""),
                    job.status, len(job.outputs) if job.status is JobStatus.DONE else 0)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()
            self._since = ""
        self.save()
        self._notify()

    # ---- reading -----------------------------------------------------
    @property
    def since(self) -> str:
        return self._since

    def rows(self) -> list[dict]:
        """One dict per provider (key, name, FIELDS), sorted by name."""
        with self._lock:
            out = [{"key": k, **v} for k, v in self._data.items()]
        return sorted(out, key=lambda r: r["name"].lower())

    def totals(self) -> dict[str, int]:
        tot = _empty()
        for row in self.rows():
            for f in FIELDS:
                tot[f] += row[f]
        return tot

    def snapshot(self) -> dict:
        return {"since": self._since, "providers": self.rows(), "totals": self.totals()}

    # ---- change notification ----------------------------------------
    def subscribe(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[], None]) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("Stats listener failed")


_default: StatsStore | None = None


def default_stats() -> StatsStore:
    """The app-wide store at ``<app data>/stats.json`` (created on first use)."""
    global _default
    if _default is None:
        from src import config
        _default = StatsStore(config.app_data_dir() / "stats.json")
    return _default


def install(store: StatsStore | None = None) -> StatsStore:
    """Count every finished queue job into ``store`` (the app-wide one by default)."""
    from src.gen.queue import add_finish_hook
    store = store or default_stats()
    add_finish_hook(store.on_job_finished)
    return store
