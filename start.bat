@echo off
cd /d "%~dp0"
start "" "http://localhost:8081"
python -m uvicorn server:app --host 127.0.0.1 --port 8081
