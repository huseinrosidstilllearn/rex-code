@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
  call .venv\Scripts\activate.bat
)

python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload %*
