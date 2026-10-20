"""Run one external command, stream its output lines, kill it on stop.

``run_command`` is the only place that starts processes, so tests swap the
``popen`` argument (or the module-level ``POPEN``) for a fake.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Sequence

from src.gen.provider import ProviderError, StopRequested

log = logging.getLogger(__name__)

POPEN = subprocess.Popen
TAIL_LINES = 15


def _creationflags() -> int:
    # Don't flash a console window for each ffmpeg call on Windows.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def run_command(cmd: Sequence[str | Path], on_line: Callable[[str], None] | None = None,
                should_stop: Callable[[], bool] = lambda: False, cwd: Path | None = None,
                popen=None, poll: float = 0.2) -> list[str]:
    """Run ``cmd``; feed each stdout/stderr line to ``on_line``.

    Returns the last output lines. Raises ``StopRequested`` if ``should_stop``
    turns true (the process is killed), ``ProviderError`` on a non-zero exit.
    """
    args = [str(c) for c in cmd]
    log.info("Run: %s", subprocess.list2cmdline(args))
    try:
        proc = (popen or POPEN)(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            cwd=str(cwd) if cwd else None, creationflags=_creationflags(),
        )
    except OSError as exc:
        raise ProviderError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    tail: deque[str] = deque(maxlen=TAIL_LINES)
    done = False
    while not done:
        if should_stop():
            proc.kill()
            proc.wait()
            raise StopRequested()
        try:
            line = lines.get(timeout=poll)
        except queue.Empty:
            continue
        if line is None:
            done = True
            continue
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        if on_line:
            on_line(line)
    code = proc.wait()
    if code != 0:
        detail = next((t for t in reversed(tail) if t and "=" not in t), "") or (tail[-1] if tail else "")
        raise ProviderError(f"{Path(args[0]).stem} exited with code {code}: {detail}".rstrip(": "))
    return list(tail)


def capture(cmd: Sequence[str | Path], timeout: float = 60, run=None) -> str:
    """Run a short command (ffprobe) and return its stdout."""
    args = [str(c) for c in cmd]
    try:
        result = (run or subprocess.run)(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL, creationflags=_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{Path(args[0]).stem} timed out") from exc
    except OSError as exc:
        raise ProviderError(f"Could not start {Path(args[0]).name}: {exc}") from exc
    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        raise ProviderError(f"{Path(args[0]).stem} failed: {err[-1] if err else result.returncode}")
    return result.stdout
