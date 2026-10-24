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


def target_rects(window, page, grab_root, target, split=False):
    """The bounding rect of the targets, or with ``split`` one rect per widget (touching ones merged)."""
    from PySide6.QtCore import QPoint, QRect

    targets = target if isinstance(target, list) else [target]
    rects = []
    for t in targets:
        w = resolve(window, page, t)
        if not hasattr(w, "mapTo"):
            raise TypeError(f"{t!r} is not a widget ({type(w).__name__})")
        if not w.isVisible():
            raise RuntimeError(f"{t!r} is not visible")
        rects.append(QRect(w.mapTo(grab_root, QPoint(0, 0)), w.size()))
    if not split:
        out = rects[0]
        for r in rects[1:]:
            out = out.united(r)
        return [out]
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                if rects[i].adjusted(-14, -14, 14, 14).intersects(rects[j]):
                    rects[i] = rects[i].united(rects.pop(j))
                    merged = True
                    break
            if merged:
                break
    return rects


# ---- drawing ---------------------------------------------------------------
# Each callout is a tight box around its target plus a label pill ("3  Match refs")
# placed in free space nearby, with an arrow from the pill to the box.
PILL_H = 26
BIG = 0.08  # targets covering more of the image than this get their pill inside


def _pill_size(fm, c) -> tuple[int, int]:
    return BADGE + 10 + fm.horizontalAdvance(c["label"]) + 12, PILL_H


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


def _candidates(box, w, h, big: bool, img_w: int = 0, img_h: int = 0, gutter: int = 0):
    """Pill top-left corners around ``box``, nearest first, then spots in the margin lined up with it."""
    from PySide6.QtCore import QRect

    out = []
    for d in (22, 40, 64, 96, 140, 200, 270):
        cx, cy = box.center().x() - w // 2, box.center().y() - h // 2
        out += [
            QRect(cx, box.top() - d - h, w, h), QRect(cx, box.bottom() + d, w, h),
            QRect(box.right() + d, cy, w, h), QRect(box.left() - d - w, cy, w, h),
            QRect(box.left(), box.top() - d - h, w, h), QRect(box.right() - w, box.top() - d - h, w, h),
            QRect(box.left(), box.bottom() + d, w, h), QRect(box.right() - w, box.bottom() + d, w, h),
            QRect(box.right() + d, box.top(), w, h), QRect(box.left() - d - w, box.top(), w, h),
        ]
    if gutter:  # the label column on the right, level with the target (tried first)
        x = img_w - gutter - MARGIN // 2
        cy = box.center().y() - h // 2
        out = [QRect(x, cy + dy, w, h) for dy in (0, -30, 30, -60, 60)] + out
    if img_w:  # margin rows above and below the shot, lined up with the target
        cx = box.center().x() - w // 2
        rows = [MARGIN_TB // 2 - h // 2, img_h - MARGIN_TB // 2 - h // 2]
        for y in rows:
            for dx in (0, -80, 80, -160, 160, -260, 260):
                out.append(QRect(cx + dx, y, w, h))
    if big:  # inside the region, near its top and left edges
        for fx in (0.05, 0.3, 0.5, 0.7):
            for fy in (0.1, 0.3, 0.5, 0.7, 0.9):
                out.append(QRect(box.left() + int((box.width() - w) * fx), box.top() + int((box.height() - h) * fy), w, h))
    return out


def _busy(img, r) -> int:
    """How much is drawn under ``r``: sampled pixels that differ from the area's main colour."""
    from collections import Counter

    px = [img.pixel(x, y) & 0xFFFFFF for y in range(r.top(), r.bottom(), 3) for x in range(r.left(), r.right(), 3)]
    if not px:
        return 0
    base = Counter(px).most_common(1)[0][0]
    br, bg, bb = base >> 16, (base >> 8) & 255, base & 255
    return sum(1 for v in px if abs((v >> 16) - br) + abs(((v >> 8) & 255) - bg) + abs((v & 255) - bb) > 40)


def _seg_hits_rect(p1, p2, r) -> bool:
    """Does the segment p1-p2 pass through rect ``r`` (sampled)?"""
    import math

    n = max(2, int(math.hypot(p2.x() - p1.x(), p2.y() - p1.y()) / 3))
    for k in range(1, n):
        t = k / n
        x, y = p1.x() + (p2.x() - p1.x()) * t, p1.y() + (p2.y() - p1.y()) * t
        if r.contains(int(x), int(y)):
            return True
    return False


def _segs_cross(a1, a2, b1, b2) -> bool:
    def side(p, q, r):
        return (q.x() - p.x()) * (r.y() - p.y()) - (q.y() - p.y()) * (r.x() - p.x())
    return side(a1, a2, b1) * side(a1, a2, b2) < 0 and side(b1, b2, a1) * side(b1, b2, a2) < 0


def _arrows(pill, boxes):
    """(start, tip) of each arrow from ``pill`` to its boxes; none for a pill inside its box."""
    from PySide6.QtCore import QPointF, QRectF

    out = []
    for box in boxes:
        if box.contains(pill):
            continue
        tip = _edge_point(QRectF(box), QPointF(pill.center()))
        out.append((_edge_point(QRectF(pill), tip), tip))
    return out


def _path_busy(img, a, b) -> int:
    """Edges the segment a-b crosses (text, borders), sampled every 4 px."""
    import math

    n = max(1, int(math.hypot(b.x() - a.x(), b.y() - a.y()) / 4))
    hits, prev = 0, None
    for k in range(n + 1):
        x = int(a.x() + (b.x() - a.x()) * k / n)
        y = int(a.y() + (b.y() - a.y()) * k / n)
        if not (0 <= x < img.width() and 0 <= y < img.height()):
            continue
        v = img.pixel(x, y)
        lum = ((v >> 16) & 255) + ((v >> 8) & 255) + (v & 255)
        if prev is not None and abs(lum - prev) > 60:
            hits += 1
        prev = lum
    return hits


def _place_pill(img, own, anchor, size, img_rect, all_boxes, pills, arrows, big, gutter=0):
    import math

    best, best_score = None, None
    for i, r in enumerate(_candidates(anchor, *size, big, img.width(), img.height(), gutter)):
        if not img_rect.adjusted(4, 4, -4, -4).contains(r):
            continue
        if any(r.adjusted(-6, -6, 6, 6).intersects(p) for p in pills):
            continue
        inside = any(b.contains(r) for b in own)
        if not inside and any(r.adjusted(-3, -3, 3, 3).intersects(b) for b in own):
            continue
        if inside and not big:
            continue
        others = [b for b in all_boxes if not any(b is o for o in own)]
        # a pill on another callout's target would read as belonging to it
        if any(r.adjusted(-4, -4, 4, 4).intersects(b) for b in others):
            continue
        mine = _arrows(r, own)
        length = sum(math.hypot(t.x() - s0.x(), t.y() - s0.y()) for s0, t in mine)
        cross = sum(1 for s0, t in mine for b in others if _seg_hits_rect(s0, t, b))
        cross += sum(1 for s0, t in mine for a1, a2 in arrows if _segs_cross(s0, t, a1, a2))
        cross += sum(1 for s0, t in mine for p in pills if _seg_hits_rect(s0, t, p))
        score = (cross * 2000 + _busy(img, r) * 40 + length * 1.5 + i * 0.1
                 + sum(_path_busy(img, s0, t) for s0, t in mine) * 25)
        if best_score is None or score < best_score:
            best, best_score = r, score
    return best


MARGIN = 44  # plain border round each shot, so labels near the edges don't cover the UI
MARGIN_TB = 64  # taller above and below: room for a row of labels


def _add_margin(img, rects, gutter: int = 0):
    """Plain border round the shot; ``gutter`` widens the right side into a label column."""
    from PySide6.QtGui import QColor, QImage, QPainter

    out = QImage(img.width() + 2 * MARGIN + gutter, img.height() + 2 * MARGIN_TB, QImage.Format.Format_ARGB32)
    out.fill(QColor(img.pixel(1, 1)).darker(135))
    p = QPainter(out)
    p.drawImage(MARGIN, MARGIN_TB, img)
    p.end()
    return out, [(c, [r.translated(MARGIN, MARGIN_TB) for r in rs]) for c, rs in rects]


def draw_callouts(img, rects: list[tuple[dict, object]], gutter: int = 0) -> None:
    import math

    from PySide6.QtCore import QPointF, QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    accent = QColor(ACCENT)
    label_font = QFont("Segoe UI")
    label_font.setPixelSize(13)
    label_font.setBold(True)
    fm = QFontMetrics(label_font)
    img_rect = QRect(0, 0, img.width(), img.height())
    area = img.width() * img.height()

    groups = [[r.adjusted(-c.get("pad", 2), -c.get("pad", 2), c.get("pad", 2), c.get("pad", 2)) for r in rs]
              for c, rs in rects]
    all_boxes = [b for g in groups for b in g]
    pills: list = []
    arrows: list = []
    plan = []
    for (c, _), own in zip(rects, groups):
        size = _pill_size(fm, c)
        anchor = own[0]
        for b in own[1:]:
            anchor = anchor.united(b)
        big = max(b.width() * b.height() for b in own) > BIG * area
        if "at" in c:
            cx, cy = anchor.center().x() + c["at"][0], anchor.center().y() + c["at"][1]
            pill = QRect(cx - size[0] // 2, cy - size[1] // 2, *size)
        else:
            pill = _place_pill(img, own, anchor, size, img_rect, all_boxes, pills, arrows, big, gutter)
            if pill is None:  # crowded: fall back to just above the target, kept on the image
                pill = QRect(anchor.left(), max(4, anchor.top() - 30), *size)
        pills.append(pill)
        arrows += _arrows(pill, own)
        plan.append((c, own, pill))

    # boxes first, then arrows, then pills on top so labels stay readable
    for c, own, _ in plan:
        if c.get("box", True):
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for box in own:
                p.drawRoundedRect(QRectF(box), 4, 4)
    for start, tip in arrows:
        if math.hypot(tip.x() - start.x(), tip.y() - start.y()) < 10:
            continue
        ang = math.atan2(tip.y() - start.y(), tip.x() - start.x())
        shaft_end = QPointF(tip.x() - 8 * math.cos(ang), tip.y() - 8 * math.sin(ang))
        outline = QPen(QColor(0, 0, 0, 150), 5.5)
        outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(outline)
        p.drawLine(start, shaft_end)
        line = QPen(accent, 2.5)
        line.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(line)
        p.drawLine(start, shaft_end)
        head = QPolygonF([
            tip,
            QPointF(tip.x() - 13 * math.cos(ang - 0.42), tip.y() - 13 * math.sin(ang - 0.42)),
            QPointF(tip.x() - 13 * math.cos(ang + 0.42), tip.y() - 13 * math.sin(ang + 0.42)),
        ])
        p.setPen(QPen(QColor(0, 0, 0, 150), 1))
        p.setBrush(accent)
        p.drawPolygon(head)
    for c, _, pill in plan:
        pr = QRectF(pill)
        p.setPen(QPen(accent, 2))
        p.setBrush(QColor(18, 18, 22, 240))
        p.drawRoundedRect(pr, PILL_H / 2, PILL_H / 2)
        circle = QRectF(pr.left() + 2, pr.top() + 1, BADGE, BADGE)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(circle)
        p.setFont(label_font)
        p.setPen(QColor("#ffffff"))
        p.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(c["n"]))
        p.drawText(QRectF(circle.right() + 8, pr.top(), pr.width() - BADGE - 12, pr.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, c["label"])
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
                rects.append((c, [QRect(*c["rect"])]))
            else:
                rects.append((c, target_rects(window, page, root, c["target"], c.get("split", False))))
        if spec.get("crop"):
            cx, cy = spec["crop"][:2]
            img = img.copy(QRect(*spec["crop"]))
            rects = [(c, [r.translated(-cx, -cy) for r in rs]) for c, rs in rects]
        img, rects = _add_margin(img, rects, spec.get("gutter", 0))
        draw_callouts(img, rects, spec.get("gutter", 0))
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
