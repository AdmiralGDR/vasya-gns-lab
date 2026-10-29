# VASYA GNS LAB CLI launcher (PowerShell)
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = if (Test-Path "$Here\App") { "$Here\App" } else { $Here }
if (Test-Path "$App\..\State") { if (-not $env:VASYA_ROOT) { $env:VASYA_ROOT = (Resolve-Path "$App\..").Path } }
else { $env:VASYA_BUNDLE_DIR = (Resolve-Path "$App\..").Path }
$env:PYTHONPATH = "$App;$App\site-packages"
$env:PYTHONDONTWRITEBYTECODE = "1"
& "$App\python\python.exe" -m vasya @args
exit $LASTEXITCODE
