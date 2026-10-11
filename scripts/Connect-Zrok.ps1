$ErrorActionPreference = 'Stop'
$zrokExe = Join-Path $env:LOCALAPPDATA 'QRPrintInbox\tools\zrok2\2.0.8\zrok2.exe'
if (-not (Test-Path -LiteralPath $zrokExe)) {
    throw 'zrok2 2.0.8 bulunamadi. Zrok binary yolunu kontrol edin.'
}
# Read-Host keeps the token out of terminal history and repository files.
$secureToken = Read-Host 'zrok portalindaki Account Token (sohbete gondermeyin)' -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $accountToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
    if ([string]::IsNullOrWhiteSpace($accountToken)) { throw 'Token bos olamaz.' }
    $enableOutput = & $zrokExe enable $accountToken --headless --description 'QR File Inbox Windows' 2>&1
    $enableExit = $LASTEXITCODE
    if ($enableExit -ne 0) {
        throw 'Hesap baglantisi basarisiz. Portal tokenini ve internet baglantisini kontrol edin. Tokeni sohbete yapistirmayin.'
    }
    Write-Host 'zrok hesap baglantisi tamamlandi. Henuz internet tuneli acilmadi.'
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    $accountToken = $null
    $enableOutput = $null
    $secureToken.Dispose()
}
