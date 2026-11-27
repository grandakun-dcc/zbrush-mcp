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
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the ZBrush MCP virtual environment."
    }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip in the ZBrush MCP virtual environment."
}
& $python -m pip install --upgrade $Source
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install zbrush-mcp from $Source."
}
Write-Output (Join-Path $venv "Scripts\zbrush-mcp.exe")
