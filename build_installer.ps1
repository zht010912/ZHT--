param(
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')]
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $VenvPython -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$InnoCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$InnoCompiler = $InnoCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $InnoCompiler) {
    throw "未找到 Inno Setup。请安装 Inno Setup 6 后重试。"
}

& $VenvPython -m PyInstaller --noconfirm --clean --windowed --onedir --name ActionFlow --collect-data meeting_assistant --workpath build\pyinstaller --specpath build\spec --distpath dist desktop_launcher.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $InnoCompiler "/DMyAppVersion=$Version" "installer\ActionFlow.iss"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Installer = Join-Path $ProjectRoot "release\ActionFlow_Setup_v$Version.exe"
if (-not (Test-Path -LiteralPath $Installer)) {
    throw "安装包未生成：$Installer"
}
Get-Item -LiteralPath $Installer | Select-Object FullName, Length, LastWriteTime
