@echo off
setlocal
set "HERE=%~dp0"
if exist "%HERE%App\" (set "APP=%HERE%App") else (set "APP=%HERE:~0,-1%")
if exist "%APP%\..\State\" (if not defined VASYA_ROOT for %%I in ("%APP%\..") do set "VASYA_ROOT=%%~fI") else (for %%I in ("%APP%\..") do set "VASYA_BUNDLE_DIR=%%~fI")
set "PYTHONPATH=%APP%;%APP%\site-packages"
set "PYTHONDONTWRITEBYTECODE=1"
start "" "%APP%\python\pythonw.exe" -m vasya.gui %*
