$ErrorActionPreference = 'Stop'
$installedInbox = Join-Path $env:LOCALAPPDATA 'Programs\QRPrintInbox\QRPrintInbox.exe'
if (Test-Path -LiteralPath $installedInbox) {
    $stopProcess = Start-Process -FilePath $installedInbox -ArgumentList '/stop' -WindowStyle Hidden -Wait -PassThru
    if ($stopProcess.ExitCode -ne 0) { throw 'Installed inbox could not be stopped.' }
    $deadline = (Get-Date).AddSeconds(45)
    do {
        $ownedProcesses = @(Get-Process QRPrintInbox -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $installedInbox })
        if (-not $ownedProcesses.Count) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ($ownedProcesses.Count) { throw 'Close the Inbox panel and retry; background shutdown may still be running.' }
}
$sourceRoot = Split-Path -Parent $PSScriptRoot
$sourcePython = Join-Path $sourceRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $sourcePython) {
    Push-Location $sourceRoot
    try {
        & $sourcePython -m scripts.manage stop
        if ($LASTEXITCODE -ne 0) { throw 'Source inbox could not be stopped.' }
    } finally { Pop-Location }
}
foreach ($shortcutName in @('QR Print Inbox.lnk', 'QR File Inbox.lnk')) {
    $startupInbox = Join-Path ([Environment]::GetFolderPath('Startup')) $shortcutName
    if (Test-Path -LiteralPath $startupInbox) { Remove-Item -LiteralPath $startupInbox }
}
Write-Output 'Inbox stopped; automatic startup removed. Documents and settings preserved.'
