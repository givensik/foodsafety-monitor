@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem === Excel file: drag & drop onto this .bat, or type the path ===
set "XLSX=%~1"
if "%XLSX%"=="" set /p XLSX=Excel file path (drag the file here and press Enter): 
set "XLSX=%XLSX:"=%"

where python > nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found. Install from https://www.python.org/downloads/ with "Add python.exe to PATH" checked.
  pause
  exit /b 1
)

if not exist ".naver_map_saver_installed" (
  echo [SETUP] Installing playwright, openpyxl ... first run only
  python -m pip install --quiet playwright openpyxl || goto :fail
  python -m playwright install chromium || goto :fail
  echo ok> ".naver_map_saver_installed"
)

echo.
echo [1/2] Preview: search query / memo
python naver_map_saver.py "%XLSX%" --dry-run || goto :fail
echo.
set /p GO=Looks right? Start saving to Naver Map (y/n): 
if /i not "%GO%"=="y" exit /b 0

echo [2/2] Start
python naver_map_saver.py "%XLSX%"
pause
exit /b 0

:fail
echo [ERROR] Failed. Send a screenshot of this window.
pause
exit /b 1
