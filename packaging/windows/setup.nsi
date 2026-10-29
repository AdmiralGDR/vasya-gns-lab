; VASYA GNS LAB — Windows Setup (per-user, no admin). Built by scripts/build_windows.py.
; STATUS: UNVERIFIED on real Windows (built and structure-checked on Linux only).
Unicode true
!include "MUI2.nsh"
!ifndef VERSION
  !define VERSION "1.1.0"
!endif
!ifndef STAGE
  !error "pass -DSTAGE=<staged dir>"
!endif
!ifndef OUTFILE
  !define OUTFILE "VASYA-GNS-LAB-${VERSION}-Setup.exe"
!endif
Name "VASYA GNS LAB ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\VASYA-GNS-LAB"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\VASYA-GNS-LAB"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchManager
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"
!insertmacro MUI_LANGUAGE "English"

Function LaunchManager
  Exec '"$INSTDIR\App\python\pythonw.exe" "$INSTDIR\App\launch_manager.pyw"'
FunctionEnd

Section "VASYA GNS LAB Manager" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\App"
  File /r "${STAGE}\App"
  File /r "${STAGE}\Docs"
  File "${STAGE}\vasya.cmd"
  File "${STAGE}\vasya-gns-manager.cmd"
  ; images are NOT inside Setup.exe: the Manager imports them from the downloaded
  ; VASYA-GNS-LAB-${VERSION}-Linux.tar.zst parts (Home -> "Load images..."); remember where Setup ran
  FileOpen $0 "$INSTDIR\payload_source.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "VASYA GNS LAB ${VERSION}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "VASYA GNS LAB"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
  CreateShortCut "$SMPROGRAMS\VASYA GNS LAB.lnk" "$INSTDIR\App\python\pythonw.exe" '"$INSTDIR\App\launch_manager.pyw"' "$INSTDIR\App\vasya\data\icons\vasya-gns-lab.ico"
  CreateShortCut "$DESKTOP\VASYA GNS LAB.lnk" "$INSTDIR\App\python\pythonw.exe" '"$INSTDIR\App\launch_manager.pyw"' "$INSTDIR\App\vasya\data\icons\vasya-gns-lab.ico"
SectionEnd

Section "Uninstall"
  ; 1) undo everything VASYA put into GNS3 (receipt-checked), report to Documents
  ExecWait '"$INSTDIR\App\python\python.exe" "$INSTDIR\App\launch_cli.py" uninstall --level components -y' $0
  CopyFiles /SILENT "$INSTDIR\Reports\UNINSTALL_REPORT.md" "$DOCUMENTS\VASYA-GNS-LAB-UNINSTALL-REPORT.md"
  ; 2) remove the VASYA folder itself (projects of a separate GNS3 install live outside it)
  Delete "$SMPROGRAMS\VASYA GNS LAB.lnk"
  Delete "$DESKTOP\VASYA GNS LAB.lnk"
  DeleteRegKey HKCU "${UNKEY}"
  ; only the folders VASYA itself creates (never "RMDir /r $INSTDIR": the user may have
  ; picked a shared parent directory); GNS3\projects is kept if it holds anything
  RMDir /r "$INSTDIR\App"
  RMDir /r "$INSTDIR\Store"
  RMDir /r "$INSTDIR\State"
  RMDir /r "$INSTDIR\Logs"
  RMDir /r "$INSTDIR\Reports"
  RMDir /r "$INSTDIR\Demos"
  RMDir /r "$INSTDIR\Desktop"
  RMDir /r "$INSTDIR\Cache"
  RMDir /r "$INSTDIR\Imports"
  RMDir /r "$INSTDIR\Docs"
  RMDir "$INSTDIR\GNS3\projects"
  RMDir /r "$INSTDIR\GNS3\images"
  RMDir /r "$INSTDIR\GNS3\appliances"
  Delete "$INSTDIR\GNS3\*.conf"
  RMDir "$INSTDIR\GNS3"
  Delete "$INSTDIR\vasya.cmd"
  Delete "$INSTDIR\vasya-gns-manager.cmd"
  Delete "$INSTDIR\payload_source.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /REBOOTOK "$INSTDIR"
SectionEnd
