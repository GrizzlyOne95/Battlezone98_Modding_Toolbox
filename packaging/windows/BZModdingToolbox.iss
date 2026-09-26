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
; * adds "Open in BZ Modding Toolbox" to the right-click menu of folders and
;   folder backgrounds (optional, on by default), opening the folder as a project;
; * adds a Start menu shortcut, and optionally a desktop shortcut and the
;   install folder on PATH (the bztoolbox command line);
; * upgrades in place: the same AppId finds the previous install, and the old
;   library folder is cleared first so no stale files are left behind. An
;   installed copy turns the wizard into an update: it reuses the previous
;   install mode (UsePreviousPrivileges), folder and options, skips the licence
;   and options pages, says "Update from <old> to <new>", and asks before
;   replacing a newer version with an older one;
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
#define MenuKey "BZModdingToolbox"
#define MenuText "Open in BZ Modding Toolbox"

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
Name: "contextmenu"; Description: "Add ""Open in BZ Modding Toolbox"" to the right-click menu of folders"; GroupDescription: "Explorer:"
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
; Explorer right-click: %1 is the folder clicked on, %V the folder whose background was clicked.
; (Windows 11 lists these under "Show more options".)
Root: HKA; Subkey: "Software\Classes\Directory\shell\{#MenuKey}"; ValueType: string; ValueName: ""; ValueData: "{#MenuText}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\{#MenuKey}"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\{#MenuKey}\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" gui --project ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#MenuKey}"; ValueType: string; ValueName: ""; ValueData: "{#MenuText}"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#MenuKey}"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#MenuKey}\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" gui --project ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UserEnvKey = 'Environment';
  MachineEnvKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  NewVersion = '{#AppVersion}';

var
  { version of the copy already installed in this install mode, '' if none }
  PreviousVersion: String;

function UninstallKey: String;
begin
  Result := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
end;

function IsUpdate: Boolean;
begin
  Result := PreviousVersion <> '';
end;

{ Next number of a dotted version, removed from Version ('1.2.3' -> 1, Version = '2.3'). }
function TakeVersionPart(var Version: String): Integer;
var
  Dot: Integer;
begin
  Dot := Pos('.', Version);
  if Dot = 0 then
  begin
    Result := StrToIntDef(Trim(Version), 0);
    Version := '';
  end else
  begin
    Result := StrToIntDef(Trim(Copy(Version, 1, Dot - 1)), 0);
    Version := Copy(Version, Dot + 1, Length(Version));
  end;
end;

{ -1, 0 or 1 as version A is older than, the same as or newer than B. }
function CompareVersions(A, B: String): Integer;
var
  I, PartA, PartB: Integer;
begin
  Result := 0;
  for I := 1 to 3 do
  begin
    PartA := TakeVersionPart(A);
    PartB := TakeVersionPart(B);
    if PartA > PartB then Result := 1;
    if PartA < PartB then Result := -1;
    if Result <> 0 then Exit;
  end;
end;

{ Update-specific wording: "Update" for a newer version, "Reinstall" for the same one. }
function UpdateVerb: String;
begin
  if CompareVersions(NewVersion, PreviousVersion) = 0 then Result := 'Reinstall' else Result := 'Update';
end;

function InitializeSetup: Boolean;
var
  Root: Integer;
begin
  Result := True;
  { The install mode is settled by now: UsePreviousPrivileges picked the mode
    of an existing install, so its uninstall entry is in this root. }
  if IsAdminInstallMode then Root := HKEY_LOCAL_MACHINE else Root := HKEY_CURRENT_USER;
  if not RegQueryStringValue(Root, UninstallKey, 'DisplayVersion', PreviousVersion) then
    PreviousVersion := '';
  if not IsUpdate then
  begin
    Log('No previous install found: installing ' + NewVersion + '.');
    Exit;
  end;
  Log('Found installed version ' + PreviousVersion + ': updating to ' + NewVersion + '.');
  if CompareVersions(NewVersion, PreviousVersion) < 0 then
    Result := SuppressibleMsgBox('{#AppName} ' + PreviousVersion + ' is installed, which is newer than this setup (' +
                                 NewVersion + ').' + #13#10#13#10 + 'Replace it with the older version ' + NewVersion + '?',
                                 mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDYES) = IDYES;
end;

procedure InitializeWizard;
begin
  if IsUpdate then
    WizardForm.Caption := UpdateVerb + ' - {#AppName}';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { An update keeps the licence already accepted and the options chosen at
    install (Setup remembers them), so it goes straight to "Ready to update". }
  Result := IsUpdate and ((PageID = wpLicense) or (PageID = wpSelectTasks));
end;

procedure CurPageChanged(CurPageID: Integer);
var
  FromTo: String;
begin
  if not IsUpdate then Exit;
  if UpdateVerb = 'Update' then
    FromTo := ' from ' + PreviousVersion + ' to ' + NewVersion
  else
    FromTo := ' ' + NewVersion;
  case CurPageID of
    wpReady:
      begin
        WizardForm.PageNameLabel.Caption := 'Ready to ' + Lowercase(UpdateVerb);
        WizardForm.PageDescriptionLabel.Caption := UpdateVerb + ' {#AppName}' + FromTo + '.';
        WizardForm.ReadyLabel.Caption := 'Click ' + UpdateVerb + ' to continue. Your settings and project profiles are kept.';
        WizardForm.NextButton.Caption := '&' + UpdateVerb;
      end;
    wpInstalling:
      begin
        WizardForm.PageNameLabel.Caption := 'Updating';
        WizardForm.PageDescriptionLabel.Caption := 'Please wait while Setup updates {#AppName}' + FromTo + '.';
      end;
    wpFinished:
      begin
        { shorter than the default texts, so the launch checkbox below them stays clear }
        WizardForm.FinishedHeadingLabel.Caption := '{#AppName} is up to date';
        WizardForm.FinishedLabel.Caption := 'Setup has updated {#AppName} to ' + NewVersion + '.';
      end;
  end;
end;

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

procedure RemoveContextMenu;
var
  Root: Integer;
begin
  if IsAdminInstallMode then Root := HKEY_LOCAL_MACHINE else Root := HKEY_CURRENT_USER;
  RegDeleteKeyIncludingSubkeys(Root, 'Software\Classes\Directory\shell\{#MenuKey}');
  RegDeleteKeyIncludingSubkeys(Root, 'Software\Classes\Directory\Background\shell\{#MenuKey}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('addtopath') then
      AddToPath(ExpandConstant('{app}'))
    else
      RemoveFromPath(ExpandConstant('{app}'));
    { an upgrade that turns the menu entry off must not leave the old one behind }
    if not WizardIsTaskSelected('contextmenu') then
      RemoveContextMenu;
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
