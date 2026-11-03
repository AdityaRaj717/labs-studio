"""run_export's stall watchdog, with a fake process (no FFmpeg needed)."""

from __future__ import annotations

import threading

import pytest

from src.editor.ffmpeg import ExportError, ExportPlan, run_export


class _SilentProc:
    """Prints nothing and never exits until killed."""

    def __init__(self, *a, **k):
        self._dead = threading.Event()
        self.killed = False
        self.stdin = None
        self.stdout = self

    def __iter__(self):
        self._dead.wait(10)
        return iter(())

    def kill(self):
        self.killed = True
        self._dead.set()

    def wait(self, timeout=None):
        self._dead.wait(10)
        return -9


def test_stalled_export_raises(tmp_path):
    plan = ExportPlan(["-i", "x"], "g", [], ["-an", str(tmp_path / "out.mp4")], 2.0, None, None, [])
    made = []

    def popen(*a, **k):
        made.append(_SilentProc())
        return made[0]

    with pytest.raises(ExportError, match="stalled"):
        run_export("ffmpeg", plan, tmp_path / "w", popen=popen, stall_seconds=0.5)
    assert made[0].killed
