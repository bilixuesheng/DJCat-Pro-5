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
DefaultDirName={code:GetDefaultDir}
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
Name: "chinesesimplified"; MessagesFile: "scripts\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist/djcat.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]

function GetDriveType(lpRootPathName: String): UINT;
  external 'GetDriveTypeW@kernel32.dll stdcall';

const
  DRIVE_FIXED = 3;

function GetDefaultDir(Param: String): String;
var
  UserName: String;
begin
  UserName := GetUserNameString;
  if DirExists('D:\') and (GetDriveType('D:\') = DRIVE_FIXED) then
    Result := 'D:\Users\' + UserName + '\AppData\Local\Programs\DJCat Pro'
  else
    Result := ExpandConstant('{autopf}\DJCat Pro');
end;

procedure DriveButtonClick(Sender: TObject);
var
  DriveLetter: Char;
  UserName: String;
begin
  DriveLetter := Chr(TNewButton(Sender).Tag);
  UserName := GetUserNameString;
  WizardForm.DirEdit.Text := DriveLetter + ':\Users\' + UserName + '\AppData\Local\Programs\DJCat Pro';
end;

procedure InitializeWizard();
var
  HintLabel: TNewStaticText;
  DriveButton: TNewButton;
  I: Integer;
  DriveLetter: Char;
  DriveRoot: String;
  ButtonLeft: Integer;
  UserName: String;
  ButtonCaption: String;
  ButtonWidth: Integer;
begin
  UserName := GetUserNameString;

  { Hint about Deep Freeze }
  HintLabel := TNewStaticText.Create(WizardForm);
  HintLabel.Parent := WizardForm.SelectDirPage;
  HintLabel.Caption :=
    '如果计算机使用了冰点还原等系统还原软件，建议将电教猫安装在不会被还原的分区' + #13#10 +
    '（通常为 D 盘或其他非系统盘）。';
  HintLabel.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(8);
  HintLabel.Left := WizardForm.DirEdit.Left;
  HintLabel.Width := WizardForm.DirEdit.Width;
  HintLabel.WordWrap := True;
  HintLabel.AutoSize := True;

  { Drive selection buttons }
  ButtonLeft := WizardForm.DirEdit.Left;
  for I := Ord('C') to Ord('Z') do
  begin
    DriveLetter := Chr(I);
    DriveRoot := DriveLetter + ':\';
    if DirExists(DriveRoot) and (GetDriveType(DriveRoot) = DRIVE_FIXED) then
    begin
      DriveButton := TNewButton.Create(WizardForm);
      DriveButton.Parent := WizardForm.SelectDirPage;
      DriveButton.Top := HintLabel.Top + HintLabel.Height + ScaleY(8);
      DriveButton.Left := ButtonLeft;
      DriveButton.Height := ScaleY(23);

      if DriveLetter = 'C' then
      begin
        ButtonCaption := DriveLetter + ': (可能被还原)';
        ButtonWidth := ScaleX(120);
      end
      else
      begin
        ButtonCaption := DriveLetter + ': 盘';
        ButtonWidth := ScaleX(60);
      end;

      DriveButton.Width := ButtonWidth;
      DriveButton.Caption := ButtonCaption;
      DriveButton.Tag := I;
      DriveButton.OnClick := @DriveButtonClick;

      ButtonLeft := ButtonLeft + ButtonWidth + ScaleX(8);
    end;
  end;
end;
