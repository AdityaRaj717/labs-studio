"""Regenerate the help guide's screenshots (Phase 15).

    python tools/make_help_screenshots.py            # every spec
    python tools/make_help_screenshots.py flow-image # just these

For every ``help/en/img/specs/<name>.json`` (format: ``src/help/shots.py``) this
builds the real main window hidden with demo data, opens the page, grabs it
with ``QWidget.grab()``, draws the numbered callouts and writes
``help/en/img/<name>.png``.

It never touches your real app data: ``APPDATA`` points at a scratch folder
(``--scratch``, default ``D:\\tmp_render\\help_shots`` or the system temp folder)
and the QApplication is not named LabsStudio, so ``config.app_data_dir()`` uses
that folder. Demo projects, prompts and characters contain no account data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if os.name != "nt":
    # On Windows the native platform renders text with ClearType/DirectWrite; the offscreen
    # platform's unhinted FreeType text came out blurry. Windows stay hidden (WA_DontShowOnScreen).
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LANG_DIR = ROOT / "help" / "en"
ACCENT = "#ff5a36"
BADGE = 24

DEMO_PROMPTS = [
    "Mia waves from the door of the Bunker at dawn, soft mist",
    "Captain Rook studies a paper map by candlelight in the Bunker",
    "a red fox in fresh snow, low sun, shallow depth of field",
    "a lighthouse at dusk, long exposure, calm sea",
    "Mia and Captain Rook share a can of beans, warm light",
    "an old tram in the rain, neon reflections, night",
]


def _default_scratch() -> Path:
    d = Path("D:/tmp_render/help_shots")
    return d if Path("D:/").exists() else Path(tempfile.gettempdir()) / "labs_help_shots"


# ---- demo data -------------------------------------------------------------
def _demo_image(path: Path, color: str, label: str, size=(512, 512)) -> Path:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

    img = QImage(*size, QImage.Format.Format_RGB32)
    p = QPainter(img)
    grad = QLinearGradient(0, 0, size[0], size[1])
    grad.setColorAt(0, QColor(color))
    grad.setColorAt(1, QColor(color).darker(220))
    p.fillRect(img.rect(), grad)
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI")
    f.setPixelSize(size[1] // 8)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRect(0, 0, *size), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    return path


def _write_settings(appdata: Path) -> None:
    """Settings with neutral paths and no account data."""
    data = {
        "theme": "dark",
        "language": "en",
        "web": {
            "profile_dir": r"C:\Users\you\AppData\Local\LabsStudio\browser-profile",
            "diag_dir": r"C:\Users\you\AppData\Local\LabsStudio\diagnose",
        },
        "webhook": {"token": ""},
    }
    folder = appdata / "LabsStudio"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_demo(scratch: Path):
    """Projects and the character/scene library, created once per run."""
    from src import config, projects
    from src.characters import store as char_store

    settings = config.settings()
    store = projects.install(settings)
    default = store.list()[0]
    for name in ("Episode 1", "Episode 2"):
        store.create(name)
    ep2 = store.find("Episode 2")
    ep2.set_flow("https://flow.google.com/project/demo-episode-2", "Episode 2")
    default.set_flow("https://flow.google.com/project/demo-default", "Default")
    store.activate(ep2.id)

    imgs = scratch / "demo_images"
    chars = char_store.default_store()
    mia = chars.add("Mia", notes="Early 30s, short dark hair, red scarf, olive parka. Calm and curious.",
                    images=[_demo_image(imgs / "mia.png", "#c0504d", "Mia")])
    chars.add("Captain Rook", notes="Grey beard, navy coat with brass buttons, tired eyes.",
              images=[_demo_image(imgs / "rook.png", "#4f6fb0", "Rook")])
    chars.set_flow(mia.id, ep2.flow_url, "Mia")
    scenes = char_store.scene_store()
    scenes.add("Bunker", notes="A concrete bunker lit by candles, shelves of tins, a steel door.",
               images=[_demo_image(imgs / "bunker.png", "#7a6a4f", "Bunker", (768, 432))])
    return store


def setup_demo_rows(window, page) -> None:
    """Prompt rows in several states, as if a batch had partly run."""
    from src.gen.models import JobStatus

    page.clear()  # the project keeps rows between shots
    jobs = page.add_prompts(DEMO_PROMPTS)
    page.match_characters()
    out = Path(os.environ["APPDATA"]).parents[1] / "demo_images"
    states = [JobStatus.DONE, JobStatus.DONE, JobStatus.DONE, JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PENDING]
    for i, (job, st) in enumerate(zip(jobs, states)):
        job.status = st
        if st is JobStatus.DONE:
            job.progress = 1.0
            job.outputs = [_demo_image(out / f"out_{i}.png", "#3d7a6a", str(i + 1), (256, 256))]
        elif st is JobStatus.RUNNING:
            job.progress = 0.45
    from src.gen.queue import count_statuses

    page.model.refresh_all()
    page.stats_header._elapsed = 214.0  # as if the batch had run for 3:34
    page.stats_header.update_stats(count_statuses(page.jobs))


def setup_characters(window, page) -> None:
    page.list.setCurrentRow(0)


def setup_projects(window, page) -> None:
    page.refresh()
    page.table.selectRow(0)


def setup_settings_api(window, page) -> None:
    page.tabs.setCurrentIndex(0)


def setup_settings_web(window, page) -> None:
    from src.ui.pages.web_sessions_tab import WebSessionsTab

    for i in range(page.tabs.count()):
        if isinstance(page.tabs.widget(i), WebSessionsTab):
            page.tabs.setCurrentIndex(i)
            return
    raise RuntimeError("Web Sessions tab not found")


def setup_log(window, page) -> None:
    import logging

    page.view.clear()  # drop the startup lines, which show the scratch folder
    log = logging.getLogger("src.ui.generator.page")
    for line in ("Page: flow_image", "Imported 6 prompt(s)", "Characters attached to 4 row(s)",
                 "Queue started: 6 job(s)", "Job 1 done in 64 s (1 output)", "Job 2 done in 71 s (1 output)"):
        log.info(line)


def setup_workflow(window, page) -> None:
    from PySide6.QtCore import Qt

    view = page.view
    rect = view.scene().itemsBoundingRect().adjusted(-60, -60, 60, 60)
    view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
    if view.transform().m11() > 1.0:  # never blow the nodes up
        view.resetTransform()
    view.centerOn(rect.center())


SETUPS = {
    "demo_rows": setup_demo_rows,
    "characters": setup_characters,
    "projects": setup_projects,
    "settings_api": setup_settings_api,
    "settings_web": setup_settings_web,
    "log": setup_log,
    "workflow": setup_workflow,
}


# ---- targets ---------------------------------------------------------------
def _child(obj, segment: str):
    from PySide6.QtWidgets import QWidget

    if "[" in segment and segment.endswith("]"):
        cls, idx = segment[:-1].split("[", 1)
        found = [w for w in obj.findChildren(QWidget) if type(w).__name__ == cls or w.metaObject().className() == cls]
        return found[int(idx)]
    if "{" in segment and segment.endswith("}"):
        cls, cond = segment[:-1].split("{", 1)
        attr, _, value = cond.partition("=")
        for w in obj.findChildren(QWidget):
            if type(w).__name__ != cls and w.metaObject().className() != cls:
                continue
            got = getattr(w, attr, None)
            got = got() if callable(got) else got
            if str(got) == value:
                return w
        raise LookupError(f"no {cls} with {attr}={value}")
    if isinstance(obj, dict):
        return obj[segment]
    got = getattr(obj, segment)
    return got() if callable(got) and not hasattr(got, "metaObject") else got


def resolve(window, page, target: str):
    obj = window if target.startswith("window:") else page
    path = target.split(":", 1)[1] if target.startswith("window:") else target
    for seg in path.split("/"):
        obj = _child(obj, seg)
    return obj


def target_rect(window, page, grab_root, target):
    from PySide6.QtCore import QPoint, QRect

    targets = target if isinstance(target, list) else [target]
    rect = QRect()
    for t in targets:
        w = resolve(window, page, t)
        if not hasattr(w, "mapTo"):
            raise TypeError(f"{t!r} is not a widget ({type(w).__name__})")
        if not w.isVisible():
            raise RuntimeError(f"{t!r} is not visible")
        r = QRect(w.mapTo(grab_root, QPoint(0, 0)), w.size())
        rect = r if rect.isNull() else rect.united(r)
    return rect


# ---- drawing ---------------------------------------------------------------
def _badge_pos(rect, where: str, pad: int):
    from PySide6.QtCore import QPoint

    h = BADGE // 2
    r = rect.adjusted(-pad, -pad, pad, pad)
    return {
        "tl": QPoint(r.left(), r.top()), "tr": QPoint(r.right(), r.top()),
        "bl": QPoint(r.left(), r.bottom()), "br": QPoint(r.right(), r.bottom()),
        "left": QPoint(r.left() - h - 2, r.center().y()), "right": QPoint(r.right() + h + 2, r.center().y()),
        "top": QPoint(r.center().x(), r.top() - h - 2), "bottom": QPoint(r.center().x(), r.bottom() + h + 2),
    }[where]


def _clamp(pt, w, h):
    from PySide6.QtCore import QPoint

    m = BADGE // 2 + 1
    return QPoint(min(max(pt.x(), m), w - m), min(max(pt.y(), m), h - m))


def _edge_point(rect, toward):
    """Where the line from the rect centre to ``toward`` leaves the rect."""
    from PySide6.QtCore import QPointF

    c = QPointF(rect.center())
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return c
    sx = (rect.width() / 2) / abs(dx) if dx else float("inf")
    sy = (rect.height() / 2) / abs(dy) if dy else float("inf")
    s = min(sx, sy, 1.0)
    return QPointF(c.x() + dx * s, c.y() + dy * s)


def draw_callouts(img, rects: list[tuple[dict, object]]) -> None:
    import math

    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    accent = QColor(ACCENT)
    pen = QPen(accent, 2.5)
    for c, rect in rects:
        pad = c.get("pad", 3)
        if c.get("shape", "box") == "box":
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(rect.adjusted(-pad, -pad, pad, pad)), 6, 6)
            centre = _badge_pos(rect, c.get("badge", "tl"), pad)
        else:
            dx, dy = c["from"]
            centre = rect.center()
            centre.setX(centre.x() + dx)
            centre.setY(centre.y() + dy)
            centre = _clamp(centre, img.width(), img.height())
            tip = _edge_point(rect.adjusted(-pad, -pad, pad, pad), centre)
            ang = math.atan2(tip.y() - centre.y(), tip.x() - centre.x())
            start = QPointF(centre.x() + math.cos(ang) * BADGE / 2, centre.y() + math.sin(ang) * BADGE / 2)
            line = QPen(accent, 3)
            line.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(line)
            p.drawLine(start, tip)
            head = QPolygonF([
                tip,
                QPointF(tip.x() - 12 * math.cos(ang - 0.45), tip.y() - 12 * math.sin(ang - 0.45)),
                QPointF(tip.x() - 12 * math.cos(ang + 0.45), tip.y() - 12 * math.sin(ang + 0.45)),
            ])
            p.setBrush(accent)
            p.drawPolygon(head)
        centre = _clamp(centre, img.width(), img.height())
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(accent)
        p.drawEllipse(QPointF(centre), BADGE / 2, BADGE / 2)
        f = QFont("Segoe UI")
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(centre.x() - BADGE / 2, centre.y() - BADGE / 2, BADGE, BADGE),
                   Qt.AlignmentFlag.AlignCenter, str(c["n"]))
    p.end()


# ---- one screenshot --------------------------------------------------------
def make_window(features: str, size):
    from src import theme
    from src.app import register_pages
    from src.projects import store as current_store
    from src.ui.main_window import MainWindow
    from PySide6.QtWidgets import QApplication

    os.environ["LABS_STUDIO_FEATURES"] = "all" if features == "all" else "flow"
    theme.apply_theme(QApplication.instance(), "dark")
    window = MainWindow()
    window.attach_projects(current_store())
    register_pages(window)
    window.resize(*size)
    return window


def shoot(name: str, spec: dict, out_dir: Path) -> Path:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    window = make_window(spec.get("features", "flow"), spec.get("size", [1280, 800]))
    try:
        window.switch_page(spec["page"])
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        page = window.page(spec["page"])
        for _ in range(3):
            app.processEvents()
        if spec.get("setup"):
            SETUPS[spec["setup"]](window, page)
        for _ in range(5):
            app.processEvents()
        root = page if spec.get("grab") == "page" else window
        img = root.grab().toImage()
        rects = []
        for c in spec.get("callouts", []):
            if "rect" in c:
                rects.append((c, QRect(*c["rect"])))
            else:
                rects.append((c, target_rect(window, page, root, c["target"])))
        draw_callouts(img, rects)
        if spec.get("crop"):
            img = img.copy(QRect(*spec["crop"]))
        out = out_dir / f"{name}.png"
        img.save(str(out))
        return out
    finally:
        for p in window.pages.values():
            if callable(getattr(p, "shutdown", None)):
                p.shutdown()
        window.hide()
        window.deleteLater()
        app.processEvents()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="spec names (default: all)")
    ap.add_argument("--scratch", type=Path, default=_default_scratch(), help="scratch folder for demo app data")
    args = ap.parse_args(argv)

    scratch: Path = args.scratch
    if scratch.exists():
        shutil.rmtree(scratch)
    appdata = scratch / "AppData" / "Roaming"  # reads like a normal %APPDATA% in the Projects shot
    os.environ["APPDATA"] = str(appdata)
    _write_settings(appdata)
    from src.ui.log_panel import setup_logging

    setup_logging(scratch / "logs")  # so the Detailed Log page has lines to show

    from PySide6.QtWidgets import QApplication

    from src.help.shots import load_specs, validate_spec

    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("LabsStudioHelpShots")  # not LabsStudio: keep app_data_dir() on APPDATA
    from src.i18n import set_language

    set_language("en")
    build_demo(scratch)

    specs = load_specs(LANG_DIR)
    names = args.names or list(specs)
    failed = 0
    for name in names:
        spec = specs.get(name)
        if spec is None:
            print(f"! {name}: no spec")
            failed += 1
            continue
        errors = validate_spec(spec)
        if errors:
            print(f"! {name}: " + "; ".join(errors))
            failed += 1
            continue
        try:
            out = shoot(name, spec, LANG_DIR / "img")
            print(f"  {out.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001 - report every broken spec, then fail
            print(f"! {name}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"{len(names) - failed} of {len(names)} screenshots written")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
