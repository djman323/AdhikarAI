param(
    [int]$BackendPort = 5000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "Ensuring Python virtual environment and dependencies are set up..."
if (-not (Test-Path $venvPython)) {
    py -m venv .venv
}

& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r requirements.txt

Write-Host "Starting Adhikar AI backend on http://127.0.0.1:$BackendPort"
$env:PORT = "$BackendPort"
& $venvPython AdhikarAI.py
