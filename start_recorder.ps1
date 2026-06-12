$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BundledPython = "C:\Users\SEASUN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path -LiteralPath $BundledPython) {
    & $BundledPython "$Root\run.py" @args
    exit $LASTEXITCODE
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
    & py -3 "$Root\run.py" @args
    exit $LASTEXITCODE
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & python "$Root\run.py" @args
    exit $LASTEXITCODE
}

Write-Error "Python 3 was not found. Install Python 3.10+ or run with the bundled Codex Python path."
