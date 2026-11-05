; Builds RebeccaSetup.exe with Inno Setup (the GitHub workflow runs this after PyInstaller).
#ifndef AppVersion
  #define AppVersion "dev"
#endif

[Setup]
AppName=Rebecca
AppVersion={#AppVersion}
AppPublisher=Rebecca
DefaultDirName={localappdata}\Programs\Rebecca
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_out
OutputBaseFilename=RebeccaSetup
SetupIconFile=assets\rebecca.ico
UninstallDisplayIcon={app}\Rebecca.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "startup"; Description: "Start Rebecca when I sign in"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\Rebecca\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Rebecca"; Filename: "{app}\Rebecca.exe"
Name: "{autodesktop}\Rebecca"; Filename: "{app}\Rebecca.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Rebecca"; ValueData: """{app}\Rebecca.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\Rebecca.exe"; Description: "Start Rebecca now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userprofile}\.rebecca.log"
