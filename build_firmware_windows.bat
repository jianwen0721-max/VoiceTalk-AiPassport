@echo off
setlocal
cd /d "%~dp0"
where idf.py >nul 2>nul
if errorlevel 1 (
  echo ERROR: idf.py not found.
  echo Open "ESP-IDF 5.5.3 CMD" from the ESP-IDF installation, then run this file again.
  pause
  exit /b 1
)
call tools\validate.sh --firmware
if errorlevel 1 (
  echo Firmware build failed. Please copy the errors above when asking for help.
  pause
  exit /b 1
)
echo.
echo Build complete: %CD%\build\FoloToy-AI-Passport-full.bin
pause
