# Building the Windows app and installer

## Why PyInstaller (not Nuitka)
- PySide6 is covered by PyInstaller's maintained hooks, so Qt plugins, translations and the multimedia backend are collected without hand-written rules.
- It needs no C compiler. Nuitka compiles to C and needs MSVC or MinGW, takes many minutes per build and a lot of RAM, and its speed-up doesn't matter here: the app spends its time waiting on provider APIs and ffmpeg, not in Python.
- A clean build takes about 3 minutes here (PyInstaller 6.22, Python 3.13, PySide6).

The build is one-folder (`LabsStudio\LabsStudio.exe` plus `_internal\`), not one-file: it starts faster, never unpacks itself into `%TEMP%` on C:, and is what the installer packs. UPX is off because UPX-packed Qt DLLs are a common antivirus false positive.

## Files
| File | Purpose |
|---|---|
| `packaging\labs_studio.spec` | PyInstaller spec. Adds the modules loaded by name (`src.languages.*`, `src.workflow.nodes.*`, `keyring.backends.*`) and drops Qt modules the app doesn't use. |
| `packaging\version_info.txt` | Version resource for the exe. Keep it in step with `src/__init__.py`. |
| `packaging\installer.iss` | Inno Setup 6 script. Per-user install by default (no admin prompt), Start-menu shortcut, optional desktop icon, uninstaller. Leaves `%APPDATA%\LabsStudio` in place on uninstall. |
| `packaging\build.bat` | Runs both steps with output on D:. |

## Build (cmd.exe, from the repo root)
One-time: PyInstaller in the venv.

```bat
.venv\Scripts\python -m pip install "pyinstaller>=6.10"
```

One-time: Inno Setup 6 (only needed for the installer step).

```bat
winget install -e --id JRSoftware.InnoSetup
```

Build both:

```bat
packaging\build.bat
```

Output goes to `D:\tmp_render\labs_build` (set `LABS_BUILD_DIR` to change it):
- `dist\LabsStudio\LabsStudio.exe`: the app folder (about 165 MB).
- `installer\LabsStudio-Setup-0.1.0.exe`: the installer.
- `work\` and `pyinstaller-cache\`: build caches, safe to delete.

`build.bat` exits with code 2 if Inno Setup isn't installed (the app folder is still built).

To run the steps by hand instead:

```bat
.venv\Scripts\python -m PyInstaller packaging\labs_studio.spec --noconfirm --clean --distpath D:\tmp_render\labs_build\dist --workpath D:\tmp_render\labs_build\work
```

```bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "/DDistDir=D:\tmp_render\labs_build\dist\LabsStudio" "/DOutDir=D:\tmp_render\labs_build\installer" packaging\installer.iss
```

(If Inno Setup was installed for all users, `ISCC.exe` is under `C:\Program Files (x86)\Inno Setup 6\`.)

## Not bundled
- **ffmpeg** and **Real-ESRGAN** stay external, as in phases 7 and 8. The user installs them and sets their paths in Settings → Tools or the editor page.
- No app icon yet (the exe uses PyInstaller's default). Add `icon=` to `EXE(...)` in the spec and `SetupIconFile=` in the `.iss` once there is one.
- The exe isn't code-signed, so SmartScreen will warn on first run.

## Releasing a new version
Bump `__version__` in `src/__init__.py`, `version` in `pyproject.toml`, the numbers in `packaging\version_info.txt`, and `AppVersion` in `packaging\installer.iss`. Then run `packaging\build.bat`.
