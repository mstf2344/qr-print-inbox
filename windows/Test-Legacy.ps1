$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvExecutable = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uvExecutable)) { $uvExecutable = (Get-Command uv -ErrorAction Stop).Source }
Push-Location $projectRoot
try {
    & $uvExecutable pip install --target build/windows7/test-deps --python-version 3.8 `
        --python-platform i686-pc-windows-msvc --only-binary :all: pytest==8.3.5 httpx==0.28.1
    if ($LASTEXITCODE -ne 0) { throw 'Legacy test dependencies failed.' }
    & ./build/windows7/payload/runtime/python.exe ./windows/legacy_checks.py
    if ($LASTEXITCODE -ne 0) { throw 'Legacy runtime tests failed.' }
} finally { Pop-Location }
