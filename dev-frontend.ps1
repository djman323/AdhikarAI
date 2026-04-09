param(
    [int]$UiPort = 5500
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$uiRoot = Join-Path $root "ui"
Set-Location $uiRoot

Write-Host "Checking for npm..."
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to run the Next.js UI. Install Node.js from https://nodejs.org/ and ensure it's in your PATH."
}

Write-Host "Installing UI dependencies..."
npm install

Write-Host "Starting UI on http://127.0.0.1:$UiPort"
npm run dev -- --hostname 127.0.0.1 --port $UiPort
