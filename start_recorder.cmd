@echo off
setlocal
set "ROOT=%~dp0"
set "BUNDLED_PYTHON=C:\Users\SEASUN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PYTHON%" (
  "%BUNDLED_PYTHON%" "%ROOT%run.py" %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%ROOT%run.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%ROOT%run.py" %*
  exit /b %ERRORLEVEL%
)

echo Python 3 was not found. Install Python 3.10+ or run with the bundled Codex Python path.
exit /b 1
