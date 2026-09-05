@echo off
title Rex Code - Web Dashboard
cd /d "%~dp0"
echo ========================================================
echo   REX CODE - Web Dashboard
echo ========================================================
echo Menjalankan Web Dashboard di http://localhost:8000 ...
start http://localhost:8000
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
