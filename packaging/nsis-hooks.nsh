; Tauri 2 NSIS pre-install hook: gỡ/dọn bản Translator Box cũ (không để song song)
; và giữ nguyên thư mục dữ liệu người dùng (%USERPROFILE%\.screen-translator-2k).
!macro NSIS_HOOK_PREINSTALL
  ; Đóng tiến trình tên cũ nếu đang chạy
  nsExec::ExecToLog 'taskkill /F /IM ScreenTranslator2K.exe'

  ; Gỡ bản Inno Setup cũ (AppId {8F3B2A1C-5E4D-4C7A-9B2E-1A2B3C4D5E6F}) nếu có
  ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3B2A1C-5E4D-4C7A-9B2E-1A2B3C4D5E6F}_is1" "QuietUninstallString"
  ${If} $0 != ""
    ExecWait '$0'
  ${EndIf}
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3B2A1C-5E4D-4C7A-9B2E-1A2B3C4D5E6F}_is1" "QuietUninstallString"
  ${If} $0 != ""
    ExecWait '$0'
  ${EndIf}

  ; Gỡ bản NSIS Translator Box cũ nếu tồn tại ở vị trí mặc định
  ${If} ${FileExists} "$LOCALAPPDATA\Translator Box\uninstall.exe"
    ExecWait '"$LOCALAPPDATA\Translator Box\uninstall.exe" /S'
  ${EndIf}
  ${If} ${FileExists} "$PROGRAMFILES64\Translator Box\uninstall.exe"
    ExecWait '"$PROGRAMFILES64\Translator Box\uninstall.exe" /S'
  ${EndIf}

  ; Dọn lối tắt cũ và mục khởi động cùng Windows cũ (nếu còn sót)
  Delete "$DESKTOP\Translator Box.lnk"
  Delete "$SMSTARTUP\Translator Box.lnk"
  RMDir /r "$SMPROGRAMS\Translator Box"
  SetShellVarContext all
  Delete "$DESKTOP\Translator Box.lnk"
  Delete "$SMSTARTUP\Translator Box.lnk"
  RMDir /r "$SMPROGRAMS\Translator Box"
  SetShellVarContext current

  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Translator Box"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TranslatorBox"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "ScreenTranslator2K"
!macroend
