@echo off
REM Install aop-node Windows service (requires Administrator).
REM Bypass ExecutionPolicy for this one script only.
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-service.ps1" %*
exit /b %ERRORLEVEL%
