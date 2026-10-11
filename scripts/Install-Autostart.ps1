$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run uv sync --locked first.' }
$startupPath = [Environment]::GetFolderPath('Startup')
if (-not $startupPath) { throw 'Windows Startup folder could not be resolved.' }
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut((Join-Path $startupPath 'QR File Inbox.lnk'))
$shortcut.TargetPath = $pythonPath
$shortcut.Arguments = '-m backend.supervisor'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7
$shortcut.Description = 'QR File Inbox - start the upload service at sign-in'
$shortcut.Save()
Write-Output 'Autostart installed for this Windows user. No admin rights or password required.'
