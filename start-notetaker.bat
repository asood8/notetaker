@echo off
rem Double-click this to use notetaker. Closing the window stops it.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\notetaker.exe" (
  echo.
  echo   notetaker is not set up yet on this computer.
  echo   Double-click setup.bat first, then come back here.
  echo.
  pause
  exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Ollama is not installed, and notetaker needs it to run the model.
  echo   Install it from https://ollama.com/download, then run setup.bat again.
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting notetaker. Your browser should open in a moment.
echo.

".venv\Scripts\notetaker.exe" serve

rem Only reached if the server stops on its own, which usually means a problem.
echo.
echo   notetaker has stopped.
pause
