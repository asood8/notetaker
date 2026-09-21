@echo off
rem One-time setup. Double-click this once, then use start.bat from then on.
setlocal
cd /d "%~dp0"

echo.
echo   Setting up notetaker. This only needs doing once.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   Python is not installed, or Windows cannot find it.
  echo.
  echo   Install Python 3.11 or newer from https://www.python.org/downloads/
  echo   During the install, tick "Add python.exe to PATH".
  echo   Then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo   Creating a private Python environment...
  python -m venv .venv
  if errorlevel 1 goto failed
)

echo   Installing notetaker and what it needs...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e ".[web]"
if errorlevel 1 goto failed

where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo   notetaker is installed, but it still needs Ollama to run the model.
  echo.
  echo   Install it from https://ollama.com/download
  echo   Then run this file again to fetch the model.
  echo.
  pause
  exit /b 1
)

ollama list 2>nul | findstr /i "llama3.2" >nul
if errorlevel 1 (
  echo   Downloading the llama3.2 model. This is about 2 GB and takes a while...
  ollama pull llama3.2
  if errorlevel 1 goto failed
) else (
  echo   The llama3.2 model is already here.
)

echo.
echo   All done. Double-click start.bat whenever you want to make cards.
echo.
pause
exit /b 0

:failed
echo.
echo   Something went wrong above. The messages usually say what.
echo.
pause
exit /b 1
