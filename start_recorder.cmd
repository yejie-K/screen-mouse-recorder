@echo off
setlocal
set "ROOT=%~dp0"
set "RUNTIME_PYTHON=%ROOT%.runtime\python\python.exe"
set "PYTHONDONTWRITEBYTECODE=1"

if exist "%RUNTIME_PYTHON%" (
  "%RUNTIME_PYTHON%" "%ROOT%run.py" %*
  if errorlevel 1 pause
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 --version >nul 2>nul
  if %ERRORLEVEL%==0 (
    py -3 "%ROOT%run.py" %*
    if errorlevel 1 pause
    exit /b %ERRORLEVEL%
  )
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python --version >nul 2>nul
  if %ERRORLEVEL%==0 (
    python "%ROOT%run.py" %*
    if errorlevel 1 pause
    exit /b %ERRORLEVEL%
  )
)

where python3 >nul 2>nul
if %ERRORLEVEL%==0 (
  python3 --version >nul 2>nul
  if %ERRORLEVEL%==0 (
    python3 "%ROOT%run.py" %*
    if errorlevel 1 pause
    exit /b %ERRORLEVEL%
  )
)

echo Python 3 was not found.
echo Put Python at ".runtime\python\python.exe" or install Python 3.10+ and run:
echo python -m pip install -r requirements.txt
pause
exit /b 1
