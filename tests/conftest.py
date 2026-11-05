"""Shared fixtures: offscreen Qt so GUI tests run headless."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Tests cover every page and provider; tests of the Flow-only switch set it themselves.
os.environ.setdefault("LABS_STUDIO_FEATURES", "all")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # Delete leftover widgets while Python still runs, so interpreter shutdown does not
    # run event filters on half-deleted objects (it crashed 2 runs in 5 without this).
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _library_stores(tmp_path, monkeypatch):
    """Keep the app-wide character and scene libraries out of the real app data."""
    from src.characters import store

    monkeypatch.setattr(store, "_default", store.CharacterStore(tmp_path / "_lib" / "characters"))
    monkeypatch.setattr(store, "_scenes", store.CharacterStore(tmp_path / "_lib" / "scenes", kind="scene"))
