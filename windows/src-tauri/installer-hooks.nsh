; Uninstall leaves no Open at login behind: tauri-plugin-autostart writes the value "Roadster" under HKCU Run
; (and Task Manager's StartupApproved copy when the user toggles it there). Not when updating (/UPDATE, as Tauri's
; own template does for the Run value). An install over an older version runs the older uninstaller without /UPDATE:
; the app puts the Run value back at its next launch when settings.json says Open at login is on (main.rs).
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Roadster"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "Roadster"
  ${EndIf}
!macroend
