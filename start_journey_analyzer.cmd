@echo off
setlocal
set "ROOT=%~dp0"
set "RUNTIME_PYTHONW=%ROOT%.runtime\python\pythonw.exe"
set "RUNTIME_PYTHON=%ROOT%.runtime\python\python.exe"
set "PYTHONDONTWRITEBYTECODE=1"

if exist "%RUNTIME_PYTHONW%" (
  start "" "%RUNTIME_PYTHONW%" "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

if exist "%RUNTIME_PYTHON%" (
  start "" "%RUNTIME_PYTHON%" "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pyw -3 "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pythonw "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  start "Journey Analyzer" /min py -3 "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  start "Journey Analyzer" /min python "%ROOT%tools\serve_journey_workspace.py" %*
  exit /b 0
)

echo Python 3 was not found.
echo Put Python at ".runtime\python\python.exe" or install Python 3.10+.
pause
exit /b 1
