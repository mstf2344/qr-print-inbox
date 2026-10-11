$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvExecutable = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uvExecutable)) { $uvExecutable = (Get-Command uv -ErrorAction Stop).Source }
Push-Location $projectRoot
try {
    & $uvExecutable run python windows/build_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Runtime build failed.' }
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
    New-Item -ItemType Directory -Force -Path 'dist' > $null
    & $compiler /nologo /target:winexe /platform:x86 /optimize+ /utf8output `
        /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll `
        /r:System.Security.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
        /resource:build\windows7\payload.zip,payload.zip `
        /win32manifest:windows\app.manifest `
        /out:dist\QRPrintInbox-Kurulum.exe windows\Inbox.cs
    if ($LASTEXITCODE -ne 0) { throw 'EXE build failed.' }
    Get-FileHash -LiteralPath 'dist/QRPrintInbox-Kurulum.exe' -Algorithm SHA256 |
        Format-List Algorithm,Hash
    Write-Output 'EXE built. No account keys or customer files are embedded.'
} finally { Pop-Location }

