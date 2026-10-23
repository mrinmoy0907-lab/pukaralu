@echo off
REM Run the automated tests (backend pytest + frontend unit tests).
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
call ".venv\Scripts\activate.bat" || (echo Run setup_windows.bat first & pause & exit /b 1)
pushd backend & python -m pytest -q & popd
pushd frontend & call npm test & popd
pause
