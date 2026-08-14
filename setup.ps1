param()

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[1/2] 创建虚拟环境 .venv" -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "[2/2] 安装依赖" -ForegroundColor Cyan
& $VenvPython -m pip install -r requirements.txt

Write-Host "环境准备完成。下一步运行 .\run.ps1" -ForegroundColor Green

