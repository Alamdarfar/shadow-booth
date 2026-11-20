@echo off
rem Starts Shadow Booth on http://localhost:8765 and opens it in Chrome (or the default browser).
cd /d "%~dp0"
start "" chrome "http://localhost:8765" 2>nul || start "" "http://localhost:8765"
".venv\Scripts\python.exe" -m http.server 8765 --bind 127.0.0.1
