param()

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$BaseTemp = Join-Path $ProjectRoot ".test-tmp"

Set-Location -LiteralPath $ProjectRoot
& $Python -m pytest -p no:cacheprovider --basetemp $BaseTemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python scripts\verify_submission.py
exit $LASTEXITCODE

