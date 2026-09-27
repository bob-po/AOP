@echo off
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-aop-node.ps1" %*
exit /b %ERRORLEVEL%
