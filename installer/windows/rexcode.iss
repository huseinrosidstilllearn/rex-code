; Inno Setup script — Rex Code Windows installer
;
; Compile with the ISCC shipped with Inno Setup 6:
;     iscc installer\windows\rexcode.iss /DAppVersion=0.3.1
;
; Version is passed on the command line (single source of truth:
; rex/__init__.py __version__). The build script does this automatically.

#define AppName "Rex Code"
#define AppExeName "rex.exe"
#ifndef AppVersion
#define AppVersion "0.3.1"
#endif

[Setup]
AppId={{8F7B2C51-9D3A-4E1B-AC2F-6C0D5B7A1E42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher=Rex Code Team
AppPublisherURL=https://github.com/huseinrosidstilllearn/rex-code
AppSupportURL=https://github.com/huseinrosidstilllearn/rex-code
AppUpdatesURL=https://github.com/huseinrosidstilllearn/rex-code
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=RexCode-Setup-v{#AppVersion}-x64
SetupIconFile=..\..\assets\icon.ico
; Wizard branding (164x314 + 55x55, classic aspect ratio; Inno scales per DPI)
WizardImageFile=..\..\assets\installer\wizard.bmp
WizardSmallImageFile=..\..\assets\installer\wizard-small.bmp
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
AllowNoIcons=yes
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Indonesian is an unofficial translation, shipped in this repo
; (installer/windows/Indonesian.isl) so builds are reproducible.
Name: "indonesian"; MessagesFile: "Indonesian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add Rex Code to the system PATH (call 'rex' from any terminal)"; \
    GroupDescription: "Additional Options:"; Flags: unchecked
Name: "explorermenu"; Description: "Add 'Open Rex Code here' to the folder right-click menu"; \
    GroupDescription: "Additional Options:"; Flags: unchecked
Name: "keepdata"; Description: "Keep user data (config, sessions, logs) when uninstalling"; \
    GroupDescription: "Additional Options:"; Flags: checkedonce

[Files]
; Onedir bundle produced by PyInstaller (dist/RexCode)
Source: "..\..\dist\RexCode\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\assets\rex-here.cmd"; DestDir: "{app}"; Flags: ignoreversion; Tasks: explorermenu

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Launch {#AppName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Launch {#AppName}"; Tasks: desktopicon

; 'Open Rex Code here' — directory background + right-click on a folder
; NOTE: Inno escapes embedded quotes by DOUBLING them ("" not \")
[Registry]
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenRexCode"; \
    ValueType: string; ValueName: "MUIVerb"; ValueData: "Open Rex Code here"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenRexCode"; \
    ValueType: string; ValueName: "Icon"; ValueData: "{app}\icon.ico"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenRexCode\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\rex-here.cmd"" ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\OpenRexCode"; \
    ValueType: string; ValueName: "MUIVerb"; ValueData: "Open Rex Code here"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\OpenRexCode"; \
    ValueType: string; ValueName: "Icon"; ValueData: "{app}\icon.ico"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\OpenRexCode\command"; \
    ValueType: string; ValueName: ""; ValueData: """{app}\rex-here.cmd"" ""%V"""; Tasks: explorermenu

[Registry]
; Append {app} to the system PATH (deduplicated via NeedsAddPath)
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath('{app}')

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove the Explorer menu entries when the task was selected (HKCU keys)
Filename: "{cmd}"; Parameters: "/C reg delete ""HKCU\Software\Classes\Directory\shell\OpenRexCode"" /f >nul 2>&1 & reg delete ""HKCU\Software\Classes\Directory\Background\shell\OpenRexCode"" /f >nul 2>&1"; Flags: runhidden; Tasks: explorermenu

[UninstallDelete]
; User data lives in %LOCALAPPDATA%\RexCode. It survives uninstall while
; "keepdata" is selected; if the user unticks it, the data is removed too.
Type: filesandordirs; Name: "{localappdata}\RexCode"; Tasks: not keepdata

[Code]
// HWND_BROADCAST is predefined by Inno Setup's Pascal Script.
const
  WM_SETTINGCHANGE = $001A;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  Result := True;
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPath) then
    Exit;
  // exact-match check, case-insensitive; ';' sentinels avoid partial matches
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvName: string;
begin
  if CurStep = ssPostInstall then      if WizardIsTaskSelected('addtopath') then
    begin
      // CastStringToInteger takes a var string (in-out), so use a variable.
      EnvName := 'Environment';
      SendMessage(HWND_BROADCAST, WM_SETTINGCHANGE, 0, CastStringToInteger(EnvName));
    end;
end;
