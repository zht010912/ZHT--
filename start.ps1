# ActionFlow 一键演示启动（Windows PowerShell）
# 用法：右键使用 PowerShell 运行，或在终端执行  .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "首次运行，正在创建虚拟环境并安装依赖..."
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

$port = 8766
Write-Host ""
Write-Host "  ActionFlow 会议协同工作台"
Write-Host "  ----------------------------------------"
Write-Host "  地址:  http://127.0.0.1:$port"
Write-Host "  停止:  Ctrl + C"
Write-Host ""
Start-Job { Start-Sleep -Seconds 2; Start-Process "http://127.0.0.1:8766" } | Out-Null
$env:APP_PORT = "$port"
.\.venv\Scripts\python.exe app.py
