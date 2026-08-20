#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "ActionFlow"
#define MyAppPublisher "ActionFlow"
#define MyAppURL "https://github.com/zht010912/ZHT--"
#define MyAppExeName "ActionFlow.exe"

[Setup]
AppId={{4D46E349-B51B-4C85-9CFE-D54642D029A4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\ActionFlow
DefaultGroupName=ActionFlow
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=ActionFlow_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\ActionFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ActionFlow"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\ActionFlow"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 ActionFlow"; Flags: nowait postinstall skipifsilent
