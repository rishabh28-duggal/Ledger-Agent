@echo off
cd /d "%~dp0"
if not exist .venv py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
.venv\Scripts\python scripts\run-local.py
pause
