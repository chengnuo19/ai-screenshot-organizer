[Setup]
AppName=AI Screenshot Organizer
AppVersion=0.2.0
DefaultDirName={autopf}\AIScreenshotOrganizer
DefaultGroupName=AI Screenshot Organizer
OutputDir=dist
OutputBaseFilename=AIScreenshotOrganizer_Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes



[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\AIScreenshotOrganizer.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AI Screenshot Organizer"; Filename: "{app}\AIScreenshotOrganizer.exe"
Name: "{autodesktop}\AI Screenshot Organizer"; Filename: "{app}\AIScreenshotOrganizer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AIScreenshotOrganizer.exe"; Description: "{cm:LaunchProgram,AI Screenshot Organizer}"; Flags: nowait postinstall skipifsilent
