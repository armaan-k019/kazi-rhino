# kazi-rhino one-step setup for Windows.
# Run from the repo folder in PowerShell:   powershell -ExecutionPolicy Bypass -File .\install.ps1
# Options are passed to kazi-setup, e.g.:    .\install.ps1 -Extras "hf,anthropic" -NoAutostart
param(
    [string]$Extras = "hf",
    [switch]$NoAutostart,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python package manager)..."
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
}

if (-not (Test-Path .venv)) { uv venv --python 3.12 }
Write-Host "Installing kazi-rhino with extras: $Extras"
uv pip install --python .venv\Scripts\python.exe -e ".[$Extras]"

$setupArgs = @()
if ($NoAutostart) { $setupArgs += "--no-autostart" }
if ($DryRun) { $setupArgs += "--dry-run" }
& .venv\Scripts\python.exe -m rhino_ai_mods.setup_cli @setupArgs
