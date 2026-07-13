@echo off
REM Serves the static site and opens it in your browser.
cd /d "%~dp0\.."
start "" http://localhost:8766
".venv\Scripts\python" -m http.server 8766 --directory public
