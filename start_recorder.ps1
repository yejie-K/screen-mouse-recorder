$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimePython = Join-Path $Root ".runtime\python\python.exe"
$ScriptArgs = $args
$env:PYTHONDONTWRITEBYTECODE = "1"

function Invoke-RecorderPython {
    param([string] $PythonExe)
    & $PythonExe "$Root\run.py" @ScriptArgs
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Read-Host "Press Enter to close"
    }
    exit $code
}

if (Test-Path -LiteralPath $RuntimePython) {
    Invoke-RecorderPython $RuntimePython
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
    & py -3 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        & py -3 "$Root\run.py" @args
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            Read-Host "Press Enter to close"
        }
        exit $code
    }
}

foreach ($name in @("python", "python3")) {
    $Python = Get-Command $name -ErrorAction SilentlyContinue
    if ($Python) {
        & $name --version *> $null
        if ($LASTEXITCODE -eq 0) {
            Invoke-RecorderPython $name
        }
    }
}

Write-Host "Python 3 was not found."
Write-Host "Put Python at .runtime\python\python.exe or install Python 3.10+ and run:"
Write-Host "python -m pip install -r requirements.txt"
Read-Host "Press Enter to close"
exit 1
