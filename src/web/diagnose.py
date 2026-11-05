"""Snapshot Flow for fixing the UI contract: the engine's doctor report and a screenshot."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def diag_root() -> Path:
    from src import config

    return Path(config.get("web.diag_dir", r"D:\\glabs_web\\diag"))


def diagnose(site: str, backend=None, root: Path | None = None) -> Path:
    """Write ``<diag_dir>/<site>-<time>/doctor.json``; it also names the screenshot."""
    if backend is None:
        from src.web.flow_mcp import flow_mcp

        backend = flow_mcp()
    folder = (root or diag_root()) / f"{site}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"doctor": backend.call_tool("flow_doctor", {}, 120),
              "screenshot": backend.call_tool("flow_screenshot", {"name": "diagnose"}, 30).get("screenshot")}
    (folder / "doctor.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("Diagnose snapshot for %s saved to %s", site, folder)
    return folder
