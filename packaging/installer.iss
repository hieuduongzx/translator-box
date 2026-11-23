; Inno Setup script cho Translator2k (Rust + Tauri 2).
#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif

#define AppName "Translator2k"
#define AppId "Translator2k"
#define Publisher "hieuduongzx"
#define ExeName "Translator2k.exe"
#define RepoUrl "https://github.com/hieuduongzx/translator-box"

[Setup]
AppId={{8F3B2A1C-5E4D-4C7A-9B2E-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=Translator2k-Windows-x64-{#AppVersion}
SetupIconFile=..\src-tauri\icons\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "vi"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo lối tắt ngoài Desktop"; GroupDescription: "Lối tắt:"
Name: "startupicon"; Description: "Khởi động cùng Windows"; GroupDescription: "Tùy chọn:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\ScreenTranslator2K.exe"
Type: files; Name: "{autodesktop}\Translator Box.lnk"
Type: files; Name: "{userdesktop}\Translator Box.lnk"
Type: files; Name: "{commondesktop}\Translator Box.lnk"
Type: files; Name: "{autostartup}\Translator Box.lnk"
Type: files; Name: "{userstartup}\Translator Box.lnk"
Type: files; Name: "{commonstartup}\Translator Box.lnk"
Type: filesandordirs; Name: "{autoprograms}\Translator Box"
Type: filesandordirs; Name: "{userprograms}\Translator Box"
Type: filesandordirs; Name: "{commonprograms}\Translator Box"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Translator Box"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "TranslatorBox"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "ScreenTranslator2K"; Flags: deletevalue

[Files]
Source: "..\src-tauri\target\release\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{group}\Gỡ cài đặt {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon
Name: "{autostartup}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "Mở {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#ExeName}"; Flags: nowait runasoriginaluser; Check: WizardSilent
