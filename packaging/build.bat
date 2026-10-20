@echo off
rem Build LabsStudio (PyInstaller one-folder) and its installer (Inno Setup 6).
rem Run from the repo root in cmd.exe:  packaging\build.bat
rem Output and caches go to D:\tmp_render\labs_build (C: stays clean).
setlocal
set OUT=D:\tmp_render\labs_build
if not "%LABS_BUILD_DIR%"=="" set OUT=%LABS_BUILD_DIR%
set PYINSTALLER_CONFIG_DIR=%OUT%\pyinstaller-cache

if not exist .venv\Scripts\python.exe (
  echo Run this from the repo root, after creating .venv.
  exit /b 1
)

.venv\Scripts\python -m PyInstaller --version >nul 2>&1 || .venv\Scripts\python -m pip install "pyinstaller>=6.10"
if errorlevel 1 exit /b 1

.venv\Scripts\python -m PyInstaller packaging\labs_studio.spec --noconfirm --clean --log-level WARN --distpath "%OUT%\dist" --workpath "%OUT%\work"
if errorlevel 1 exit /b 1
echo App folder: %OUT%\dist\LabsStudio

set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
  echo Inno Setup 6 not found, skipped the installer. Install it with:
  echo   winget install -e --id JRSoftware.InnoSetup
  exit /b 2
)
"%ISCC%" /Q "/DDistDir=%OUT%\dist\LabsStudio" "/DOutDir=%OUT%\installer" packaging\installer.iss
if errorlevel 1 exit /b 1
echo Installer: %OUT%\installer
endlocal
