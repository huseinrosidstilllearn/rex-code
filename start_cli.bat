@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

python cli.py %*
