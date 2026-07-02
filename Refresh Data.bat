@echo off
REM Re-downloads sources (cached) and rebuilds public/data/*.json.
cd /d "%~dp0"
".venv\Scripts\python" -m engine.run
echo.
echo Done. Restart "Start Melbourne Property" or refresh your browser.
pause
