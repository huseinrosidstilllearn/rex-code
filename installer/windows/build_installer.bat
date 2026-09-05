@echo off
rem ============================================================
rem Rex Code — one-command Windows installer build
rem
rem   1. PyInstaller: source -> dist\RexCode\rex.exe (onedir)
rem   2. Inno Setup : dist\RexCode -> dist\installer\RexCode-Setup-vX.Y.Z-x64.exe
rem
rem Usage: double-click, or run from a terminal:
rem   installer\windows\build_installer.bat
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0..\.."

set VENV_PY=.venv\Scripts\python.exe
set ISCC_DEFAULT=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

if not exist "%VENV_PY%" (
  echo [ERROR] .venv\Scripts\python.exe not found. Run from the repo with the venv created.
  exit /b 1
)

rem --- 1. PyInstaller build (with clean) -----------------------
echo [1/3] Cleaning previous build artifacts...
if exist build\pyinstaller rmdir /s /q build\pyinstaller
if exist dist\RexCode rmdir /s /q dist\RexCode
echo [1/3] Building bundle with PyInstaller...
"%VENV_PY%" -m PyInstaller installer\windows\rex.spec --noconfirm --distpath dist --workpath build\pyinstaller
if errorlevel 1 (
  echo [ERROR] PyInstaller build failed.
  exit /b 1
)

rem --- 2. Smoke test the frozen exe ----------------------------
echo [2/3] Smoke-testing dist\RexCode\rex.exe --version ...
dist\RexCode\rex.exe --version
if errorlevel 1 (
  echo [ERROR] Frozen exe smoke test failed.
  exit /b 1
)

rem --- 3. Inno Setup compile ------------------------------------
echo [3/3] Compiling installer with Inno Setup...
rem NOTE: use goto-style checks here — the default path contains "(x86)",
rem and expanding it inside a parenthesized if-block breaks batch parsing.
set "ISCC=%ISCC_DEFAULT%"
if exist "%ISCC%" goto have_iscc
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" goto have_iscc
echo [ERROR] Inno Setup 6 not found. Install it with:
echo   winget install -e --id JRSoftware.InnoSetup
exit /b 1
:have_iscc

rem Read the version from rex/__init__.py so the installer name matches the app.
for /f "tokens=2 delims== " %%v in ('type rex\__init__.py ^| findstr /C:"__version__"') do set APPVER=%%~v
set APPVER=%APPVER:"=%

"%ISCC%" /DAppVersion=%APPVER% installer\windows\rexcode.iss
if errorlevel 1 (
  echo [ERROR] Inno Setup compile failed.
  exit /b 1
)

echo.
echo ============================================================
echo  SUCCESS
echo  Installer: dist\installer\RexCode-Setup-v%APPVER%-x64.exe
echo  Bundle:    dist\RexCode\rex.exe
echo ============================================================
endlocal
