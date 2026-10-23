@echo off
REM Scan data\sites\ and load new or changed GIS / DTM / 3D files without starting the web server.
REM (While the application is running you can also use Data Sources > Scan data folder.)
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
call ".venv\Scripts\activate.bat" || (echo Run setup_windows.bat first & pause & exit /b 1)
cd backend
python -m app.ingest
pause
