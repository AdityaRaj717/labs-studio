"""``python -m src.stitch_cli <spec.json>``: JSON lines on stdout, for the engine. Exit 1 on failure."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from src.editor.ffmpeg import ExportCancelled, ExportError
from src.editor.stitch import FfmpegNotFound, StitchSpec, stitch


def say(**line) -> None:
    print(json.dumps(line), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    stop = threading.Event()

    def watch() -> None:  # the engine cancels by closing stdin
        sys.stdin.read()
        stop.set()
    threading.Thread(target=watch, daemon=True).start()
    try:
        spec = StitchSpec.from_dict(json.loads(Path(args[0]).read_text(encoding="utf-8")))
        file = stitch(spec, lambda f: say(type="progress", progress=round(f, 3)), stop.is_set)
    except FfmpegNotFound as exc:
        say(type="error", error_code="FFMPEG_NOT_FOUND", message=str(exc))
    except ExportCancelled as exc:
        say(type="error", error_code="CANCELLED", message=str(exc))
    except (ExportError, OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        say(type="error", error_code="STITCH_FAILED", message=f"{type(exc).__name__}: {exc}")
    else:
        say(type="done", file=str(file))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
