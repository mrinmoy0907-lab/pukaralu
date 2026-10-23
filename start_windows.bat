@echo off
REM ======================================================================
REM  Pushkaralu Crowd Digital Twin - start on Windows
REM    start_windows.bat         API + built web app on http://127.0.0.1:8000
REM    start_windows.bat dev     API (port 8000) + Vite dev server (port 5173, live reload)
REM  Data in data\sites\ is scanned automatically at start-up.
REM ======================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
  echo The virtual environment is missing - running setup_windows.bat first ...
  call setup_windows.bat || exit /b 1
)
call ".venv\Scripts\activate.bat"

if /I "%~1"=="dev" goto :dev

if not exist "frontend\dist\index.html" (
  echo Building the web application ...
  pushd frontend & call npm run build & popd
)
echo.
echo Starting the Digital Twin on http://127.0.0.1:8000   (API docs: http://127.0.0.1:8000/docs)
echo Close this window or press Ctrl+C to stop.
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8000"
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
exit /b %errorlevel%

:dev
echo Starting API (8000) and Vite dev server (5173) in two windows ...
start "Pushkaralu API" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
start "Pushkaralu Web (dev)" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 8 /nobreak >nul
start http://127.0.0.1:5173
exit /b 0
