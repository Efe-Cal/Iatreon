#define MyAppName "Iatreon"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Iatreon"
#define MyAppExeName "iatreon.exe"

[Setup]
AppId={{05D208C0-FF55-4EC1-95F0-9421A13687EB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible

OutputDir=installer-output
OutputBaseFilename=Iatreon-{#MyAppVersion}-Setup

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "release\iatreon.exe"; \
    DestDir: "{app}"; \
    Flags: ignoreversion

Source: "release\python-worker\*"; \
    DestDir: "{app}\python-worker"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; \
    Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; \
    Flags: unchecked

[Icons]
Name: "{autoprograms}\Iatreon"; \
    Filename: "{app}\iatreon.exe"; \
    WorkingDir: "{app}"

Name: "{autodesktop}\Iatreon"; \
    Filename: "{app}\iatreon.exe"; \
    WorkingDir: "{app}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\iatreon.exe"; \
    Description: "Launch Iatreon"; \
    Flags: nowait postinstall skipifsilent