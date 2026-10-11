$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    New-Item -ItemType Directory -Force -Path 'build' > $null
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
    & $compiler /nologo /target:exe /platform:x86 /main:ConnectionChecks /utf8output `
        /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll `
        /r:System.Security.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
        /out:build\connection-tests.exe windows\Inbox.cs windows\ConnectionChecks.cs
    if ($LASTEXITCODE -ne 0) { throw 'Connection test compile failed.' }
    & ./build/connection-tests.exe
    if ($LASTEXITCODE -ne 0) { throw 'Connection tests failed.' }
} finally { Pop-Location }
