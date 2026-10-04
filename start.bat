@echo off
setlocal
cd /d "%~dp0"

echo.
echo ========================================================
echo   Auto Job Applier - starting your control panel
echo ========================================================
echo.

set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto START

echo Creating Python environment...
py -3 -m venv .venv

if errorlevel 1 goto ERROR_VENV

echo Installing required packages...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto ERROR_PIP

"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto ERROR_PIP

:START
echo.
echo Starting the control panel...
echo.

set "PANEL_OPEN_BROWSER=1"
"%VENV_PY%" app.py

echo.
echo The control panel has stopped.
pause
exit /b

:ERROR_VENV
echo.
echo ERROR: Could not create the Python environment.
pause
exit /b 1

:ERROR_PIP
echo.
echo ERROR: Could not install the required packages.
pause
exit /b 1