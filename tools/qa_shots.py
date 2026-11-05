"""Capture the real main window, demo data only, every page and every review state."""
import os, shutil, sys
from pathlib import Path

ROOT = Path(r"D:\Prog\labs-studio-dev")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
mode = sys.argv[2]
w, h = (int(x) for x in sys.argv[3].split("x"))
only = sys.argv[4].split(",") if len(sys.argv) > 4 else None

scratch = Path(r"D:\tmp_render\qa_shots_" + mode + sys.argv[3])
shutil.rmtree(scratch, ignore_errors=True)
appdata = scratch / "AppData" / "Roaming"
os.environ["APPDATA"] = str(appdata)
import make_help_screenshots as m
m._write_settings(appdata)
from src.ui.log_panel import setup_logging
setup_logging(scratch / "logs")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication
app = QApplication([sys.argv[0]])
app.setApplicationName("LabsStudioHelpShots")
from src.i18n import set_language
set_language("en")
m.build_demo(scratch)
win = m.make_window("all", (w, h))
from src import theme
from src.ui import kit
theme.apply_theme(app, mode)
kit.repolish_tree()
win.sidebar.update_theme_button()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(w, h)
win.show()
from src.gen.models import JobStatus
from src.ui.sidebar import NAV_KEYS


def pump():
    for _ in range(8):
        app.processEvents()


def shot(name):
    from src.ui.generator.thumbs import service
    pump(); win.grab(); service().wait()  # thumbs decode on a pool: ask, let them land, then shoot
    pump()
    win.grab().save(str(out / f"{name}.png"))
    print("ok", name)


def picture(path, a, b, n):
    """A stand-in photo: a gradient with a horizon, to judge frames on the grey."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = QImage(960, 640, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 0, 640)
    g.setColorAt(0, QColor(a)); g.setColorAt(1, QColor(b))
    p.fillRect(img.rect(), g)
    p.setBrush(QColor(20, 24, 30)); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPoint(200 + n * 83 % 560, 470), 340, 150)
    p.end()
    img.save(str(path))
    return path


PROMPTS = [f"Wide shot, dusk over the salt flats, figure {i} walking toward a parked van, long lens, dust in the low light" for i in range(1, 13)]
COLORS = [("#d98a4b", "#2b3a55"), ("#7fa8c9", "#e8d9b0"), ("#3d7a6a", "#c9d6a3"), ("#8a4f7d", "#f0b37e")]


def rows(page):
    page.clear()
    jobs = page.add_prompts(PROMPTS)
    pics = scratch / "pics"
    states = "done done done done done done failed running pending pending done done".split()
    for i, (job, st) in enumerate(zip(jobs, states)):
        job.status = JobStatus(st)
        if st == "done":
            job.progress = 1.0
            a, b = COLORS[i % 4]
            job.outputs = [picture(pics / f"p{i}.png", a, b, i)]
        if st == "running":
            job.progress = 0.45
        if st == "failed":
            job.error = "Flow refused the prompt: the request was flagged by the content filter."
    jobs[0].review = "approved"; jobs[1].review = "approved"; jobs[2].review = "rejected"
    jobs[3].origin = "agent"; jobs[3].production_id = "demo"; jobs[3].item_id = "ep01-s03"; jobs[3].review = "pending_review"
    from src.gen.models import Take
    jobs[3].takes = [Take(1, PROMPTS[3], ["ref_van.png"], "done", str(jobs[0].outputs[0]), 10, "rejected", "app",
                          "2026-11-04T10:12:00Z", "horizon too high"),
                     Take(2, PROMPTS[3] + ", lower horizon", [], "done", str(jobs[3].outputs[0]), 10)]
    jobs[3].take = jobs[3].latest_take = 2
    jobs[3].stale = "ref-van"
    page.model.refresh_all()
    page._refresh_stats()


def want(n):
    return only is None or n in only


for key in NAV_KEYS:
    if not want(key) and key != "flow_image":
        continue
    win.switch_page(key); pump()
    pg = win.page(key)
    if key == "characters": m.setup_characters(win, pg)
    if key == "projects": m.setup_projects(win, pg)
    if key == "log": m.setup_log(win, pg)
    if key == "flow_image":
        pg.clear(); pg.select_row if False else None
        if want("empty"): shot("empty")
        rows(pg)
        pg.select_row(0)
        if want("flow_image"): shot("flow_image")
    elif want(key):
        shot(key)

if want("productions"):  # S5-1: a checked plan, as flow_production_plan returns it
    pp = win.page("productions"); win.switch_page("productions"); pump()
    files = [scratch / "ep01" / n for n in ("moodboard.md", "animation.md")]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True); f.write_text("x", encoding="utf-8")
    pp.moodboard_edit.setText(str(files[0])); pp.prompts_edit.setText(str(files[1]))
    from src.ui.production.page import _mtimes
    pp.show_plan({"ok": True, "plan_id": "7f3a91c2e04b5d18", "mode": "mixed",
                  "counts": {"references": 3, "stills": 6, "animations": 6},
                  "cast": [{"id": "REF_MARA", "name": "Mara", "kind": "character"},
                           {"id": "REF_VAN", "name": "The van", "kind": "character"},
                           {"id": "REF_FLATS", "name": "Salt flats", "kind": "place"}],
                  "errors": [], "analysis_needed": [],
                  "warnings": [{"file": str(files[1]), "line": 41, "message": "ANI_06 has no refs"}],
                  "estimate": {"credits": 120, "eta_minutes": 46}},
                 tuple(map(str, files)), _mtimes(files))
    pp.cast_confirmed.setChecked(True)
    shot("productions_plan")

pg = win.page("flow_image")
win.switch_page("flow_image"); pump()
if want("running"):
    win._live_timer.stop()
    win.sidebar.set_live("flow_image", True)
    pg._production_banner = "Episode 1: 3 waiting for your review, paused: quota"
    pg._show_banner(); pg.select_row(7); shot("running")
    pg._production_banner = ""; pg._show_banner(); win.sidebar.set_live("flow_image", False)
if want("selected_failed"):
    pg.select_row(6); pg.inspector.setVisible(True); pg._refresh_take(); shot("selected_failed"); pg._update_inspector()
if want("settings_tab"):
    pg.inspector.setVisible(True); pg.inspector_tabs.setCurrentIndex(1); shot("settings_tab"); pg.inspector_tabs.setCurrentIndex(0); pg._update_inspector()
if want("audio_tab"):
    pg.inspector.setVisible(True); pg.inspector_tabs.setCurrentWidget(pg.audio_panel)
    pg.audio_panel.show_files([{"kind": "voice", "file": "C:/run/voice/001_hello.mp3", "provider": "fish", "model": "s2.1-pro-free"},
                               {"kind": "bgm", "file": "C:/run/bgm/002_rain.wav", "provider": "stability"}])
    pg.audio_panel.show_estimate(8); shot("audio_tab"); pg.inspector_tabs.setCurrentIndex(0); pg._update_inspector()
if want("assets_tab"):
    pg.inspector.setVisible(True); pg.inspector_tabs.setCurrentWidget(pg.assets_panel)
    pg.assets_panel.show_assets({"assets": [{"mediaId": "CAMSJDk3Y2E", "label": "a red fox at dawn"}, {"mediaId": "CAMSJGQ0ZjE", "label": "an owl on a branch"}],
                                 "note": "Only the grid window shows here: the newest 28 tiles."})
    shot("assets_tab"); pg.inspector_tabs.setCurrentIndex(0); pg._update_inspector()
if want("queue"):
    pg.set_view("queue", save=False); shot("queue"); pg.set_view("sheet", save=False)
if want("filter_empty"):
    for j in pg.jobs:
        pass
    pg.set_filter("failed"); shot("filter_failed")
    saved = pg.jobs[6].status; pg.jobs[6].status = JobStatus.PENDING; pg.model.refresh_all(); pg.sheet.apply_filter(); shot("filter_empty")
    pg.jobs[6].status = saved; pg.model.refresh_all(); pg.set_filter("all")
if want("viewer"):
    pg.open_viewer(0); shot("viewer_approved"); pg.viewer.step(2); shot("viewer_rejected"); pg.close_viewer()
if want("takes"):
    pg.inspector.setVisible(True); pg.inspector_tabs.setCurrentIndex(0); pg.select_row(3); pg._refresh_take()
    pg.take_panel.take_buttons[0].click(); shot("takes")
    pg.open_viewer(3); pg.viewer.toggle_compare(); shot("compare"); pg.close_viewer()
if want("video"):
    vp = win.page("flow_video"); win.switch_page("flow_video"); pump()
    vp.clear(); vp.add_prompts(PROMPTS[:4]); vp.select_row(0); vp.inspector.setVisible(True); vp._refresh_take(); shot("video")
    win.switch_page("flow_image"); pump()
if want("menu"):
    pg.select_row(4)
    menu = pg.table._build_menu(4, [4]); menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True); menu.adjustSize(); menu.show(); pump()
    menu.grab().save(str(out / "menu.png")); menu.hide(); print("ok menu")
if want("palette"):
    win.palette_.open(); shot("palette"); win.palette_.edit.setText("zzz"); shot("palette_none"); win.palette_.hide()
for p in win.pages.values():
    if callable(getattr(p, "shutdown", None)):
        p.shutdown()
win.hide()
