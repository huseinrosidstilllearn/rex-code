@echo off
rem Rex Code — "Open Rex Code here" launcher
rem Sets REX_WORKSPACE to the chosen folder so config, sessions, and logs
rem live project-scoped inside that folder, then starts the TUI.
setlocal
set "REX_WORKSPACE=%~1"
if "%REX_WORKSPACE%"=="" cd /d "%USERPROFILE%"
cd /d "%REX_WORKSPACE%" 2>nul
"%~dp0rex.exe"
endlocal
