@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard-oeffnen.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Das Bewerbungs-Dashboard konnte nicht gestartet werden ^(Code %RC%^).
  echo Details: ..\04_Agent\data\launcher.log sowie ..\04_Agent\data\server.log / server.err.log
  echo.
  pause
)
endlocal
