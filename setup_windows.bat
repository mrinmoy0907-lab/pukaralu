@echo off
REM ======================================================================
REM  Pushkaralu Crowd Digital Twin - one-time setup on Windows
REM  Creates a Python virtual environment (.venv), installs the backend,
REM  installs and builds the web frontend.
REM  Requirements: Python 3.11, 3.12 or 3.13 (64-bit) and Node.js 20+ LTS.
REM ======================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1

echo.
echo [1/5] Looking for Python 3.11 - 3.13 ...
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3.11, 3.12 or 3.13 ^(64-bit^) was not found.
  echo        Install it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  goto :fail
)
echo       using: %PY%

echo [2/5] Creating virtual environment .venv ...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat" || goto :fail
python -m pip install --upgrade pip wheel >nul || goto :fail

echo [3/5] Installing backend packages (JuPedSim, GDAL wheels, FastAPI ...) - this can take a few minutes ...
pip install -r backend\requirements-dev.txt || goto :fail

echo [4/5] Installing frontend packages ...
where npm >nul 2>&1 || (
  echo ERROR: Node.js / npm not found. Install the LTS version from https://nodejs.org/ and run this file again.
  goto :fail
)
pushd frontend
call npm install || (popd & goto :fail)

echo [5/5] Building the web application ...
call npm run build || (popd & goto :fail)
popd

if not exist ".env" copy ".env.example" ".env" >nul
if not exist "data\sites" mkdir "data\sites"

echo.
echo Setup complete. Start the application with  start_windows.bat
echo Put surveyed data into  data\sites\^<your-site^>\  (see docs\DATA_FOLDER.md)
pause
exit /b 0

:fail
echo.
echo Setup FAILED - see the messages above.
pause
exit /b 1
