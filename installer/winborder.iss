; Winborder installer.
;
; Built by tools/build_installer.py, which passes the version, the publisher and
; the executable in, so nothing here has to be kept in step by hand:
;
;   iscc /DAppVersion=2.0.0 /DCopyrightLine="..." installer\winborder.iss
;
; The install is per user on purpose. The host keeps its settings file beside
; the executable and registers itself under HKCU to start at logon, neither of
; which it can do from a per machine directory that only an administrator can
; write to.

#define AppName "Winborder"
#define AppExeName "Winborder.exe"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "Gatongone"
#endif
#ifndef CopyrightLine
  #define CopyrightLine "Copyright (C) Gatongone"
#endif
#ifndef SourceExe
  #define SourceExe "..\dist\Winborder.exe"
#endif
#ifndef SourceIcon
  #define SourceIcon "..\build\winborder.ico"
#endif

[Setup]
; The identity of the application, for upgrades and for Windows. This must never
; change, or an update installs beside the old one instead of over it.
AppId={{E0D8C398-4B3A-488D-A9E9-F9D168BBD6B4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
VersionInfoCopyright={#CopyrightLine}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile={#SourceIcon}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; The host adds this entry itself when "Start with Windows" is switched on. The
; value is not created here; naming it is what has the uninstaller remove it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#AppName}"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
