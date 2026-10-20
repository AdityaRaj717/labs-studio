; Inno Setup 6 script for Labs Studio.
; Packs the PyInstaller one-folder build into LabsStudio-Setup-<version>.exe.
;
; Build (after the PyInstaller step, see docs/phase-10-build.md):
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss
; Override the folders with /DDistDir=... /DOutDir=... if you built elsewhere.

#define AppName "Labs Studio"
#define AppVersion "0.1.0"
#define AppExe "LabsStudio.exe"
#ifndef DistDir
  #define DistDir "D:\tmp_render\labs_build\dist\LabsStudio"
#endif
#ifndef OutDir
  #define OutDir "D:\tmp_render\labs_build\installer"
#endif

[Setup]
AppId={{6D1E3C52-8F0B-4C7A-9B1E-2A4F5D6C7E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\Labs Studio
DefaultGroupName=Labs Studio
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt); the user may pick all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=LabsStudio-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Labs Studio"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\Labs Studio"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,Labs Studio}"; Flags: nowait postinstall skipifsilent

; Settings, keys (Windows Credential Manager), characters, stats and outputs live in
; %APPDATA%\LabsStudio and are left in place on uninstall on purpose.
