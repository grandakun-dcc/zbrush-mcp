param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\Grandakun-DCC\zbrush",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 9876
)

$command = Join-Path $InstallRoot "venv\Scripts\zbrush-mcp.exe"
if (-not (Test-Path -LiteralPath $command)) {
    throw "zbrush-mcp is not installed at $command"
}

& $command doctor --host $HostName --port $Port
exit $LASTEXITCODE
