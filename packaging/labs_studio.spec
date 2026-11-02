# PyInstaller spec for Labs Studio (one-folder Windows build).
#
# Build from the repo root (see docs/phase-10-build.md):
#   .venv\Scripts\python -m PyInstaller packaging\labs_studio.spec --noconfirm
#       --distpath D:\tmp_render\labs_build\dist --workpath D:\tmp_render\labs_build\work
#
# One-folder (not one-file): it starts faster, never unpacks into %TEMP% on C:,
# and is what the Inno Setup script installs.

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Loaded by name at runtime, so PyInstaller cannot see them by itself:
# languages (src/i18n.py) and keyring's Windows Credential Locker backend.
hidden = (collect_submodules("src.languages")
          + collect_submodules("keyring.backends"))

# Qt modules the app never imports; dropping them saves well over 100 MB.
qt_unused = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtQuick", "QtQuick3D", "QtQuickWidgets", "QtQml", "QtCharts", "QtDataVisualization",
    "QtGraphs", "QtPdf", "QtPdfWidgets", "QtLocation", "QtPositioning", "QtBluetooth", "QtNfc",
    "QtSensors", "QtSerialPort", "QtSql", "QtTest", "QtDesigner", "QtHelp", "QtRemoteObjects",
    "QtScxml", "QtSpatialAudio", "QtTextToSpeech", "QtVirtualKeyboard",
)]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "src", "web", "selectors", "*.json"), "src/web/selectors")],  # Phase 11
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=qt_unused + ["tkinter", "pytest", "_pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabsStudio",
    debug=False,
    strip=False,
    upx=False,          # UPX-packed Qt DLLs trigger antivirus false positives
    console=False,      # GUI app; logs go to %APPDATA%\LabsStudio\logs
    version=os.path.join(SPECPATH, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LabsStudio",
)
