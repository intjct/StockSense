; Inno Setup script — builds StockSense-Setup-x.y.z.exe from dist\StockSense
; Installs for the current user only (no admin password needed).
; Keys, portfolio and history live in %APPDATA%\StockSense, so installing over
; an old version keeps them.

#ifndef MyAppVersion
  #define MyAppVersion "1.2.0"
#endif

[Setup]
AppId={{B7D41E2A-6C3F-4A58-9E21-7F0C5D8A3B96}
AppName=StockSense
AppVersion={#MyAppVersion}
AppPublisher=StockSense
DefaultDirName={localappdata}\Programs\StockSense
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=StockSense-Setup-{#MyAppVersion}
SetupIconFile=..\assets\stocksense.ico
UninstallDisplayIcon={app}\StockSense.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "..\dist\StockSense\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\StockSense"; Filename: "{app}\StockSense.exe"
Name: "{userdesktop}\StockSense"; Filename: "{app}\StockSense.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\StockSense.exe"; Description: "Open StockSense now"; Flags: nowait postinstall skipifsilent
; updated from inside the program (it starts this installer with /RELAUNCH=1): open the new version again
Filename: "{app}\StockSense.exe"; Parameters: "--updated"; Flags: nowait; Check: ShouldRelaunch

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM StockSense.exe"; Flags: runhidden; RunOnceId: "StopStockSense"

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;
