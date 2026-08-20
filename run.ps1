param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8767
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

Set-Location -LiteralPath $ProjectRoot

if (-not $env:DEEPSEEK_API_KEY) {
    Write-Warning "未设置 DEEPSEEK_API_KEY：AI 分析会明确失败，但会议和手工行动项仍可使用。"
}

if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Listener) {
        Write-Error "端口 $Port 已被占用。请关闭占用进程，或改用 .\run.ps1 -Port 8768，并访问对应端口。"
        exit 1
    }
}

Write-Host "ActionFlow 正在启动：http://127.0.0.1:$Port" -ForegroundColor Green
& $Python -m flask --app app run --host 127.0.0.1 --port $Port
