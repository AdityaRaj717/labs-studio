"""UI performance harness (S6-1). Measurement only, never part of pytest.

    python tools/perf_ui.py <rows> <width> <out.json>

Synthetic local images, the real MainWindow offscreen (as qa_shots.py does), no network, no Flow.
Run it for the numbers on 1920x1080. Every metric is written next to its target from the master plan (S6).
Metrics that cannot be driven without app changes are null with the reason in "note".
"""
import json, os, platform, random, shutil, statistics, sys, tempfile, time
from pathlib import Path

T0 = time.perf_counter()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
rows_n = int(sys.argv[1]); width = int(sys.argv[2]); out_json = Path(sys.argv[3])
W, H = 1920, 1080
scratch = Path(tempfile.mkdtemp(prefix="perf_ui_"))
appdata = scratch / "AppData" / "Roaming"
os.environ["APPDATA"] = str(appdata)

import make_help_screenshots as m
m._write_settings(appdata)
from src.ui.log_panel import setup_logging
setup_logging(scratch / "logs")
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication([sys.argv[0]])
app.setApplicationName("LabsStudioPerf")
from src.i18n import set_language
set_language("en")
m.build_demo(scratch)

try:
    import psutil
    _proc = psutil.Process()

    def rss_mb():
        return _proc.memory_info().rss / 1048576
except ImportError:  # Windows API fallback
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    def rss_mb():
        k32, ps = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        c = PMC(); c.cb = ctypes.sizeof(c)
        ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / 1048576


def pump(n=8):
    for _ in range(n):
        app.processEvents()


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))] if s else None


def ms_since(t):
    return (time.perf_counter() - t) * 1000


results = {}


def metric(key, target, measured, unit, note=""):
    results[key] = {"measured": None if measured is None else round(measured, 2), "unit": unit,
                    "target": target, "meets_target": None, "note": note}
    print(f"{key}: {results[key]['measured']} {unit} (target {target})  {note}")


# ---- synthetic images: a few bases, hard-linked up to the row count ----------------------
def make_bases(dest: Path, count=24):
    dest.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    files = []
    for i in range(count):
        img = QImage(1376, 768, QImage.Format.Format_RGB32)
        p = QPainter(img)
        g = QLinearGradient(0, 0, 0, 768)
        g.setColorAt(0, QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        g.setColorAt(1, QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        p.fillRect(img.rect(), g)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(900):  # texture so file sizes are photo-like, not flat
            p.setBrush(QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), 90))
            p.drawEllipse(rnd.randrange(1376), rnd.randrange(768), rnd.randrange(8, 90), rnd.randrange(8, 90))
        p.end()
        if i % 3 == 0:
            path = dest / f"base{i}.png"; img.save(str(path))
        else:
            path = dest / f"base{i}.jpg"; img.save(str(path), quality=90)
        files.append(path)
    return files


t_img = time.perf_counter()
bases = make_bases(scratch / "src_imgs")
pics = scratch / "pics"; pics.mkdir()
paths = []
for i in range(rows_n):
    b = bases[i % len(bases)]
    dst = pics / f"f{i:05d}{b.suffix}"
    try:
        os.link(b, dst)
    except OSError:
        shutil.copy(b, dst)
    paths.append(dst)
img_s = time.perf_counter() - t_img
print(f"images ready: {rows_n} rows from {len(bases)} bases in {img_s:.1f}s")
img_kb = {s: round(statistics.mean(b.stat().st_size for b in bases if b.suffix == s) / 1024) for s in (".jpg", ".png")}

# ---- cold start: process start to the first painted frame -------------------------------
from src.gen.models import JobStatus
win = m.make_window("all", (W, H))
from src import theme
from src.ui import kit
theme.apply_theme(app, "dark"); kit.repolish_tree()
win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
win.resize(W, H)
win.show()
win.grab()  # forces the first complete paint
pump()
metric("cold_start_s", "<= 1.5 s", time.perf_counter() - T0 - img_s, "s",
       "script start (imports and demo setup included, synthetic image creation subtracted) to window shown and first grab, "
       "warm disk cache, offscreen (WA_DontShowOnScreen)")

# ---- first build of a page ----------------------------------------------------------------
# Pages are built lazily and the window opens on flow_image, so that build sits inside cold_start.
# The video page is the same GeneratorPage class, built here for the first time.
t = time.perf_counter()
win.switch_page("flow_video"); pump()
metric("first_page_build_ms", "<= 200 ms", ms_since(t), "ms",
       "first switch_page('flow_video') (builds a GeneratorPage, lazily) plus event pump; the image page's own build is inside cold_start_s")
win.switch_page("flow_image"); pump()
page = win.page("flow_image")
page.clear(); pump()
win._live_timer.stop()

# ---- import --------------------------------------------------------------------------------
prompts = [f"Wide shot {i}, dusk over the salt flats, figure walking toward a parked van, long lens" for i in range(rows_n)]
t = time.perf_counter()
jobs = page.add_prompts(prompts)
pump()
metric("import_rows_ms", "<= 500 ms", ms_since(t), "ms", f"page.add_prompts({rows_n}) plus event pump; rows have no outputs yet")
statuses = ["done"] * 7 + ["failed", "running", "pending"]
t = time.perf_counter()
for i, job in enumerate(jobs):
    st = statuses[i % len(statuses)]
    job.status = JobStatus(st)
    if st == "done":
        job.progress = 1.0; job.outputs = [paths[i]]
    elif st == "running":
        job.progress = 0.4
    elif st == "failed":
        job.error = "refused"
page.model.refresh_all(); page._refresh_stats(); pump()
results["import_rows_ms"]["attach_outputs_ms"] = round(ms_since(t), 2)
page.select_row(0); pump()
rss_start = rss_mb()

# ---- filter changes -------------------------------------------------------------------------
times = []
for key in ["failed", "all", "review", "all", "failed", "all"]:
    t = time.perf_counter(); page.set_filter(key); pump(); times.append(ms_since(t))
metric("filter_change_ms", "<= 50 ms", statistics.mean(times), "ms", f"set_filter plus pump, mean of {len(times)}")
results["filter_change_ms"]["worst_ms"] = round(max(times), 2)
page.set_filter("all"); pump()

# ---- scroll: step plus synchronous viewport repaint per frame, top to bottom and back, twice ----
class PaintSpy(QObject):
    def __init__(self):
        super().__init__(); self.stamps = []

    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.Paint:
            self.stamps.append(time.perf_counter())
        return False


page.set_view("sheet", save=False); pump()
sheet = page.sheet
bar = sheet.verticalScrollBar()
spy = PaintSpy(); sheet.viewport().installEventFilter(spy)
step = max(40, bar.maximum() // 240)
positions = (list(range(0, bar.maximum(), step)) + list(range(bar.maximum(), 0, -step))) * 2
frame_ms = []
for v in positions:
    t = time.perf_counter(); bar.setValue(v); sheet.viewport().repaint(); app.processEvents()
    frame_ms.append(ms_since(t))
sheet.viewport().removeEventFilter(spy)
gaps = [(b - a) * 1000 for a, b in zip(spy.stamps, spy.stamps[1:])]
metric("scroll_frame_p95_ms", "<= 20 ms", pct(frame_ms, .95), "ms",
       f"{len(frame_ms)} frames, each scrollbar step plus synchronous viewport repaint plus events (range {bar.maximum()} px, step {step}); "
       f"{len(spy.stamps)} paint events seen")
metric("scroll_frame_worst_ms", "<= 40 ms", max(frame_ms), "ms", "same frames")
if gaps:
    results["scroll_frame_p95_ms"]["paint_event_interval_p95_ms"] = round(pct(gaps, .95), 2)
    results["scroll_frame_p95_ms"]["paint_event_interval_worst_ms"] = round(max(gaps), 2)
bar.setValue(0); pump()

metric("rss_after_scroll_mb", "<= 600 MB", rss_mb(), "MB", f"RSS {rss_start:.0f} MB before scrolling; after scrolling all {rows_n} rows twice")

# ---- slider drag ------------------------------------------------------------------------------
sl = page.size_slider
lo, hi = sl.minimum(), sl.maximum()
seq = list(range(width, hi, 8)) + list(range(hi, lo, -8)) + list(range(lo, width + 1, 8))
durs = []
t0 = time.perf_counter()
for v in seq:
    t = time.perf_counter(); sl.setValue(v); sheet.viewport().repaint(); app.processEvents(); durs.append(ms_since(t))
total = time.perf_counter() - t0
metric("slider_drag_fps", ">= 30 fps", len(seq) / total, "fps",
       f"{len(seq)} steps, each setValue plus synchronous repaint; step p95 {pct(durs, .95):.1f} ms, worst {max(durs):.1f} ms")
metric("slider_drag_no_ui_decode", "no decode on the UI thread", None, "bool",
       "not measured: no decode counter without app changes; frame_pixmap decodes inside paint today (S6 code facts), so expect false")
sl.setValue(width); pump()

# ---- job update burst: 100/s for 4 s ------------------------------------------------------------
running = [j for j in jobs if j.status == JobStatus.RUNNING] or jobs[:50]
rnd = random.Random(3)
count = {"n": 0}


def fire():
    j = rnd.choice(running); j.progress = min(0.99, j.progress + 0.001)
    page.model.refresh_job(j.id)
    count["n"] += 1


timer = QTimer(); timer.setTimerType(Qt.TimerType.PreciseTimer); timer.setInterval(10); timer.timeout.connect(fire)
busy = 0.0
t0 = time.perf_counter(); timer.start()
while time.perf_counter() - t0 < 4.0:
    t = time.perf_counter(); app.processEvents(); busy += time.perf_counter() - t
    time.sleep(0.001)
timer.stop(); wall = time.perf_counter() - t0
metric("burst_100_per_s_ui_busy_pct", "< 10 %", 100 * busy / wall, "%",
       f"{count['n']} updates in {wall:.1f}s ({count['n'] / wall:.0f}/s) via model.refresh_job (filter, stats, save-timer slots and the repaints included); "
       f"busy = time inside processEvents / wall, 1 ms sleeps excluded")
pump()

# ---- 20 viewer open/close cycles ------------------------------------------------------------------
pump(); r0 = rss_mb()
vt = []
for i in range(20):
    t = time.perf_counter(); page.open_viewer((i * 37) % rows_n); pump(); vt.append(ms_since(t))
    page.close_viewer(); pump()
r1 = rss_mb()
metric("viewer_cycles_rss_growth_pct", "< 5 %", 100 * (r1 - r0) / r0, "%",
       f"RSS {r0:.0f} MB to {r1:.0f} MB over 20 open/close; open plus pump mean {statistics.mean(vt):.0f} ms, worst {max(vt):.0f} ms")

metric("thumbnail_memory_mb", "256 MB cap by bytes", None, "MB",
       "not measurable: the thumb cache has no byte accounting or cap yet (prompt_model._thumb is unbounded); S6-2 adds it")

for p in win.pages.values():
    if callable(getattr(p, "shutdown", None)):
        p.shutdown()
win.hide()

lim = {"cold_start_s": ("<=", 1.5), "first_page_build_ms": ("<=", 200), "import_rows_ms": ("<=", 500),
       "filter_change_ms": ("<=", 50), "scroll_frame_p95_ms": ("<=", 20), "scroll_frame_worst_ms": ("<=", 40),
       "slider_drag_fps": (">=", 30), "burst_100_per_s_ui_busy_pct": ("<", 10), "rss_after_scroll_mb": ("<=", 600),
       "viewer_cycles_rss_growth_pct": ("<", 5)}
for k, (op, v) in lim.items():
    x = results[k]["measured"]
    results[k]["meets_target"] = None if x is None else {"<=": x <= v, ">=": x >= v, "<": x < v}[op]

doc = {"date": time.strftime("%Y-%m-%d"), "rows": rows_n, "frame_width": width, "window": f"{W}x{H}",
       "platform": platform.platform(), "processor": platform.processor(), "python": platform.python_version(),
       "qt_platform": app.platformName(), "image_size": "1376x768", "image_mean_kb": img_kb, "metrics": results}
out_json.parent.mkdir(parents=True, exist_ok=True)
out_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")
print("wrote", out_json)
shutil.rmtree(scratch, ignore_errors=True)
