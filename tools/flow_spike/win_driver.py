"""Live window checks: the real app, real engine and real Flow, with a command file a controller feeds.

Each command is Python run on the GUI thread with `w` (the MainWindow) and helpers; modal dialogs do not block it.
"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, ".")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src import app as app_module  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402

OUT = Path(__file__).parent / "out" / "win"
OUT.mkdir(parents=True, exist_ok=True)
CMD, RES = OUT / "cmd.py", OUT / "res.json"
RES.unlink(missing_ok=True)
CMD.unlink(missing_ok=True)


def shot(widget, name):
    path = OUT / f"{name}.png"
    QApplication.processEvents()
    widget.window().screen().grabWindow(widget.window().winId()).save(str(path))
    return str(path)


def click(text, top=None):
    root = top or QApplication.activeModalWidget() or QApplication.activeWindow()
    for b in root.findChildren(QPushButton):
        if b.text().replace("&", "") == text and b.isVisible():
            b.click()
            return True
    return False


def poll(window):
    if not CMD.exists():
        return
    src = CMD.read_text(encoding="utf-8")
    CMD.unlink()
    scope = {"w": window, "shot": shot, "click": click, "app": QApplication.instance(), "time": time, "modal": QApplication.activeModalWidget}
    try:
        exec(compile(src, "cmd", "exec"), scope)  # noqa: S102 - a harness the controller alone feeds
        out = {"ok": True, "result": scope.get("result")}
    except Exception:  # noqa: BLE001
        out = {"ok": False, "error": traceback.format_exc()}
    RES.write_text(json.dumps(out, default=str), encoding="utf-8")


_show = MainWindow.show


def show(self):
    _show(self)
    self._driver = QTimer(self)
    self._driver.timeout.connect(lambda: poll(self))
    self._driver.start(200)


MainWindow.show = show
sys.exit(app_module.main([]))
