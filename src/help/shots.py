"""Screenshot specs for the help guide (Phase 15), Qt-free.

Each ``help/<lang>/img/specs/<name>.json`` describes one screenshot that
``tools/make_help_screenshots.py`` captures to ``help/<lang>/img/<name>.png``:

    {
      "page": "flow_image",            # sidebar page key to open
      "features": "flow",              # "flow" (Flow-only mode) or "all"
      "size": [1280, 800],             # window size
      "setup": "demo_rows",            # optional: a named setup step in the script
      "grab": "window",                # "window" (default) or "page"
      "crop": [0, 0, 1280, 500],       # optional, in grabbed-image pixels
      "callouts": [
        {"n": 1, "target": "config_panel", "label": "Settings"},
        {"n": 2, "target": ["btn_import", "btn_paste"], "label": "Add prompts"},
        {"n": 3, "target": "window:picker", "label": "Project", "at": [160, 40]}
      ]
    }

Every callout draws a tight box round its target (``"box": false`` leaves it
out) and a numbered label pill with an arrow to it. The pill is placed in
free space automatically; ``at: [dx, dy]`` pins its centre relative to the
target's centre instead. A list of targets gets one box round all of them;
``"split": true`` boxes each widget on its own, with an arrow to each.
``"gutter": 220`` on a spec adds a label column on the right for dense pages. ``label`` is a few words matching the numbered list
under the image in the topic.

A target is a widget path from the page: attribute names, dict keys,
``Class[i]`` (the i-th child widget of that class) or ``Class{attr=value}``
(the first child whose attribute, or method result, equals value), joined by
``/``. ``window:`` starts from the main window instead, and a list of targets
means their bounding box. ``rect: [x, y, w, h]`` (grabbed-image pixels) can
stand in for a target.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FEATURES = ("flow", "all")
GRABS = ("window", "page")
KEYS = {"page", "features", "size", "setup", "grab", "crop", "gutter", "callouts", "note"}
CALLOUT_KEYS = {"n", "target", "rect", "label", "at", "box", "split", "pad"}


def _is_int_list(v: Any, n: int) -> bool:
    return isinstance(v, list) and len(v) == n and all(isinstance(x, int) and not isinstance(x, bool) for x in v)


def validate_spec(spec: Any) -> list[str]:
    """Problems with a spec (empty list = valid)."""
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]
    errors = [f"unknown key {k!r}" for k in spec if k not in KEYS]
    if not isinstance(spec.get("page"), str) or not spec.get("page"):
        errors.append("'page' must be a page key")
    if spec.get("features", "flow") not in FEATURES:
        errors.append(f"'features' must be one of {FEATURES}")
    if spec.get("grab", "window") not in GRABS:
        errors.append(f"'grab' must be one of {GRABS}")
    if "size" in spec and not (_is_int_list(spec["size"], 2) and all(300 <= x <= 4000 for x in spec["size"])):
        errors.append("'size' must be [width, height] in pixels")
    if "crop" in spec and not (_is_int_list(spec["crop"], 4) and spec["crop"][2] > 0 and spec["crop"][3] > 0):
        errors.append("'crop' must be [x, y, width, height]")
    if "gutter" in spec and not (isinstance(spec["gutter"], int) and 0 <= spec["gutter"] <= 400):
        errors.append("'gutter' must be 0-400 pixels")
    if "setup" in spec and not isinstance(spec["setup"], str):
        errors.append("'setup' must be a name")
    callouts = spec.get("callouts", [])
    if not isinstance(callouts, list):
        return errors + ["'callouts' must be a list"]
    seen: set[int] = set()
    for i, c in enumerate(callouts):
        where = f"callout {i + 1}"
        if not isinstance(c, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors += [f"{where}: unknown key {k!r}" for k in c if k not in CALLOUT_KEYS]
        n = c.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            errors.append(f"{where}: 'n' must be a number from 1")
        elif n in seen:
            errors.append(f"{where}: number {n} is used twice")
        else:
            seen.add(n)
        target, rect = c.get("target"), c.get("rect")
        if (target is None) == (rect is None):
            errors.append(f"{where}: give exactly one of 'target' or 'rect'")
        if target is not None and not (
            (isinstance(target, str) and target)
            or (isinstance(target, list) and target and all(isinstance(t, str) and t for t in target))
        ):
            errors.append(f"{where}: 'target' must be a widget path or a list of them")
        if rect is not None and not (_is_int_list(rect, 4) and rect[2] > 0 and rect[3] > 0):
            errors.append(f"{where}: 'rect' must be [x, y, width, height]")
        label = c.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 32:
            errors.append(f"{where}: 'label' must be a short text (1-32 characters)")
        if "at" in c and not _is_int_list(c["at"], 2):
            errors.append(f"{where}: 'at' must be [dx, dy], the label's offset from the target centre")
        for flag in ("box", "split"):
            if flag in c and not isinstance(c[flag], bool):
                errors.append(f"{where}: '{flag}' must be true or false")
        if "pad" in c and not (isinstance(c["pad"], int) and 0 <= c["pad"] <= 40):
            errors.append(f"{where}: 'pad' must be 0-40")
    if seen and seen != set(range(1, len(seen) + 1)):
        errors.append("callout numbers must run 1, 2, 3… with no gaps")
    return errors


def spec_dir(lang_dir: Path) -> Path:
    return lang_dir / "img" / "specs"


def load_specs(lang_dir: Path) -> dict[str, dict]:
    """``{name: spec}`` for every spec file of a language folder."""
    out: dict[str, dict] = {}
    for path in sorted(spec_dir(lang_dir).glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out
