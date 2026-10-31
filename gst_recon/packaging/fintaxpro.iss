; Inno Setup script for FIN TAX PRO (desktop + CLI).
; Build the PyInstaller folders first (packaging\build_windows.ps1), then:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\fintaxpro.iss
; Output: dist\installer\FinTaxPro-Setup-1.3.0.exe

#define AppName "FIN TAX PRO"
#define AppVersion "1.3.0"

[Setup]
AppId={{6F1E7C1A-2E64-4C3B-9A51-3F2B9D0C7E11}
AppName={#AppName}
AppVersion={#AppVersion}
CloseApplications=force
AppPublisher=FIN TAX PRO
AppComments=Smart GST Reconciliation. Faster Compliance. Better Accuracy.
DefaultDirName={autopf}\FinTaxPro
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=FinTaxPro-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
; User data (database, backups, evidence) lives in %LOCALAPPDATA%\FinTaxPro and is never removed by uninstall.

[Code]
// Close a running FIN TAX PRO (or an open error window of it) first, so that every old program file can be
// replaced; otherwise Windows keeps the old files locked and the previous version would keep starting.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM FinTaxPro.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM FinTaxPro-GST.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

[InstallDelete]
; Remove the previous version's program files first, so no library of an older build is left behind.
; User data lives in %LOCALAPPDATA%\FinTaxPro and is not touched.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\cli\_internal"

[Files]
Source: "..\dist\FinTaxPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\FinTaxPro-GST\*"; DestDir: "{app}\cli"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}\docs"
Source: "..\docs\*.md"; DestDir: "{app}\docs"
Source: "..\docs\USER_GUIDE.html"; DestDir: "{app}\docs"
Source: "..\sample_data\*"; DestDir: "{app}\Sample files"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\FinTaxPro.exe"
Name: "{group}\{#AppName} user guide"; Filename: "{app}\docs\USER_GUIDE.html"
Name: "{group}\{#AppName} sample files"; Filename: "{app}\Sample files"
Name: "{group}\{#AppName} command line"; Filename: "{cmd}"; Parameters: "/k cd /d ""{app}\cli"" && FinTaxPro-GST.exe --help"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\FinTaxPro.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\docs\USER_GUIDE.html"; Description: "Open the user guide"; Flags: postinstall shellexec skipifsilent nowait
Filename: "{app}\FinTaxPro.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
