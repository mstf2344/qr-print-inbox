param([switch]$Live, [switch]$InterruptService, [string]$BaseUrl)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvExecutable = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uvExecutable)) { $uvExecutable = (Get-Command uv -ErrorAction Stop).Source }
if ($Live -and -not $BaseUrl) { throw 'Use -BaseUrl with your own gateway for live tests.' }
if ($InterruptService -and -not $Live) { throw 'Use -Live together with -InterruptService.' }
Push-Location $projectRoot
try {
    & $uvExecutable run ruff check backend tests scripts windows
    if ($LASTEXITCODE -ne 0) { throw 'Python lint failed.' }
    & $uvExecutable run pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    & node --check web/app.js
    if ($LASTEXITCODE -ne 0) { throw 'Client syntax failed.' }
    & node --test tests/web-flow.test.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Client retry tests failed.' }
    & npm.cmd --prefix worker test
    if ($LASTEXITCODE -ne 0) { throw 'Worker tests failed.' }
    & node --test legacy-worker/relay.test.js
    if ($LASTEXITCODE -ne 0) { throw 'Compatible relay tests failed.' }
    $parseTokens = $null
    $parseErrors = $null
    Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' | ForEach-Object {
        [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$parseTokens,[ref]$parseErrors) > $null
        if ($parseErrors.Count) { throw "PowerShell syntax failed: $($_.Name)" }
    }
    if ($Live) {
        & $uvExecutable run python -m scripts.smoke_test --base-url $BaseUrl
        if ($LASTEXITCODE -ne 0) { throw 'Live smoke test failed.' }
        if ($InterruptService) {
            & $uvExecutable run python -m scripts.release_test --base-url $BaseUrl --interrupt-service
            if ($LASTEXITCODE -ne 0) { throw 'Live interruption/concurrency test failed.' }
        }
    }
    Write-Output 'All requested checks passed.'
} finally { Pop-Location }
