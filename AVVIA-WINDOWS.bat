@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ==============================================
echo       GOLD BET PIEDIMONTE - GESTIONALE
echo ==============================================
echo.
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)
%PYTHON_CMD% --version >nul 2>&1
if ERRORLEVEL 1 (
  echo Python non trovato. Installa Python 3.11 o successivo da python.org.
  echo Se presente, spunta Add Python to PATH.
  pause
  exit /b 1
)
echo Apertura browser: http://127.0.0.1:8787
echo Lascia questa finestra aperta durante il lavoro.
echo.
start "" "http://127.0.0.1:8787"
%PYTHON_CMD% server.py
pause