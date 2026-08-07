; DJCat Pro 5 installer, based on the packaging layout used by Ghost Downloader.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.0.0.0"
#endif
#ifndef MyAppArch
  #define MyAppArch "x64compatible"
#endif
#ifndef MyAppArchName
  #define MyAppArchName "x86_64"
#endif

#define MyAppName "电教猫 Pro 5"
#define MyAppPublisher "XUESHENG"
#define MyAppURL "https://github.com/bilixuesheng/DJCat-Pro-5"
#define MyAppExeName "djcat.exe"

[Setup]
AppId={{F8AFEC7D-367E-4C7E-8079-C7D721ACF4B3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppNumericVersion}
VersionInfoProductVersion={#MyAppNumericVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
SourceDir=..
DefaultDirName={autopf}\DJCat Pro 5
DefaultGroupName=电教猫 Pro 5
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed={#MyAppArch}
ArchitecturesInstallIn64BitMode={#MyAppArch}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=DJCat-Pro-v{#MyAppVersion}-Windows-{#MyAppArchName}-Setup
SetupIconFile=app/assets/installer_logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist/djcat.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
