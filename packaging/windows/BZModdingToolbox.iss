; Windows installer for the Battlezone Modding Toolbox (Inno Setup 6.3+).
;
;   iscc /DAppVersion=1.2.3 packaging\windows\BZModdingToolbox.iss
;
; Packs the PyInstaller folder (dist\BZModdingToolbox) into
; dist\installer\BZModdingToolbox-v<version>-windows-setup.exe, which:
;
; * installs per user (no administrator prompt, %LOCALAPPDATA%\Programs) or,
;   when chosen in the first dialog or with /ALLUSERS, for all users
;   (Program Files);
; * registers with "Installed apps" / "Programs and Features" (publisher,
;   version, icon, size, help and update links) and with App Paths, so
;   "BZModdingToolbox" and "bztoolbox" start from Win+R;
; * adds a Start menu shortcut, and optionally a desktop shortcut and the
;   install folder on PATH (the bztoolbox command line);
; * upgrades in place: the same AppId finds the previous install, and the old
;   library folder is cleared first so no stale files are left behind;
; * uninstalls cleanly, and offers to delete the user's settings, project
;   profiles and saved Steam API key (bztoolbox clean-user-data).
;
; The toolbox never writes beside its executable: per-user state lives in
; %APPDATA%\BattlezoneModdingToolbox (bztoolbox/paths.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define RepoRoot AddBackslash(SourcePath) + "..\.."
#ifndef DistDir
  #define DistDir RepoRoot + "\dist\BZModdingToolbox"
#endif

#define AppName "Battlezone Modding Toolbox"
#define AppPublisher "GrizzlyOne95"
#define AppURL "https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox"
#define AppExe "BZModdingToolbox.exe"
#define CliExe "bztoolbox.exe"
; bztoolbox.APP_ID: the taskbar groups the running window with its shortcut.
#define AppUserModelID "GrizzlyOne95.BattlezoneModdingToolbox"

[Setup]
; Never change the AppId: it is how upgrades and the uninstaller find the install.
AppId={{63CD0930-D3A1-4F9C-9DFE-251D48C601EF}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppContact={#AppURL}/issues
AppComments=Battlezone 98 Redux modding: missions, worlds, assets, validation, localization and Workshop publishing.
AppCopyright=Copyright (c) {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no

LicenseFile={#RepoRoot}\LICENSE
SetupIconFile={#RepoRoot}\bztoolbox\resources\branding\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
OutputDir={#RepoRoot}\dist\installer
OutputBaseFilename=BZModdingToolbox-v{#AppVersion}-windows-setup
Compression=lzma2/max
SolidCompression=yes
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the bztoolbox command line to PATH"; GroupDescription: "Command line:"; Flags: unchecked

[InstallDelete]
; PyInstaller's library folder: an upgrade replaces it wholesale.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSING.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Comment: "Battlezone 98 Redux modding toolbox"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; HKA = HKLM for an all-users install, HKCU for a per-user one.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#CliExe}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#CliExe}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#CliExe}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UserEnvKey = 'Environment';
  MachineEnvKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';

function EnvRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKEY_LOCAL_MACHINE else Result := HKEY_CURRENT_USER;
end;

function EnvKey: String;
begin
  if IsAdminInstallMode then Result := MachineEnvKey else Result := UserEnvKey;
end;

function PathContains(const Paths, Dir: String): Boolean;
begin
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

procedure AddToPath(const Dir: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey, 'Path', Paths) then Paths := '';
  if PathContains(Paths, Dir) then Exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then Paths := Paths + ';';
  RegWriteExpandStringValue(EnvRoot, EnvKey, 'Path', Paths + Dir);
end;

procedure RemoveFromPath(const Dir: String);
var
  Paths, Wrapped: String;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey, 'Path', Paths) then Exit;
  if not PathContains(Paths, Dir) then Exit;
  Wrapped := ';' + Paths + ';';
  StringChangeEx(Wrapped, ';' + Dir + ';', ';', True);
  StringChangeEx(Wrapped, ';' + AddBackslash(Dir) + ';', ';', True);
  while (Length(Wrapped) > 0) and (Copy(Wrapped, 1, 1) = ';') do Delete(Wrapped, 1, 1);
  while (Length(Wrapped) > 0) and (Copy(Wrapped, Length(Wrapped), 1) = ';') do Delete(Wrapped, Length(Wrapped), 1);
  if Wrapped = '' then
    RegDeleteValue(EnvRoot, EnvKey, 'Path')
  else
    RegWriteExpandStringValue(EnvRoot, EnvKey, 'Path', Wrapped);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('addtopath') then
      AddToPath(ExpandConstant('{app}'))
    else
      RemoveFromPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveFromPath(ExpandConstant('{app}'));
    { Settings live outside the install folder; only delete them on request.
      bztoolbox knows every place it stores data, including the credential
      store, so let it clean up while it is still installed. }
    if (not UninstallSilent) and
       (MsgBox('Also delete your toolbox settings, project profiles and saved Steam API key?' + #13#10#13#10 +
               'Your mod folders are never touched. Choose No to keep the settings for a later reinstall.',
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    begin
      if not Exec(ExpandConstant('{app}\{#CliExe}'), 'clean-user-data --yes', '', SW_HIDE,
                  ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
        MsgBox('Some settings could not be removed. They are in ' +
               ExpandConstant('{userappdata}\BattlezoneModdingToolbox') + '.', mbInformation, MB_OK);
    end;
  end;
end;
