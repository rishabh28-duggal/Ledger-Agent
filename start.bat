@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
start http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
