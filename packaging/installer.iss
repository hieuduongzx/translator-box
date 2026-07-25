; Inno Setup script cho Screen Translator 2K.
; Biên dịch: iscc /DAppVersion=1.0.0 packaging\installer.iss
; (build.ps1 tự truyền /DAppVersion từ python-app/version.py)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "Translator Box"
#define AppId "ScreenTranslator2K"
#define Publisher "hieuduongzx"
#define ExeName "ScreenTranslator2K.exe"
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
OutputBaseFilename=TranslatorBox-Windows-x64-{#AppVersion}
SetupIconFile=..\python-app\assets\icon.ico
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

[Files]
; Toàn bộ thư mục onedir do PyInstaller sinh ra (dist\ScreenTranslator2K\...).
Source: "..\dist\ScreenTranslator2K\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{group}\Gỡ cài đặt {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon
Name: "{autostartup}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: startupicon

[Run]
; Sau khi cài (kể cả bản cập nhật im lặng) tự mở lại app.
Filename: "{app}\{#ExeName}"; Description: "Mở {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#ExeName}"; Flags: nowait runasoriginaluser; Check: WizardSilent
