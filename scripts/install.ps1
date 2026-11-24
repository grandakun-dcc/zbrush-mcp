param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\Grandakun-DCC\zbrush",
    [string]$Source = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$venv = Join-Path $InstallRoot "venv"
$python = Join-Path $venv "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venv
}

& $python -m pip install --upgrade pip
& $python -m pip install --upgrade $Source
Write-Output (Join-Path $venv "Scripts\zbrush-mcp.exe")
