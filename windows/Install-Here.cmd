@echo off
setlocal
cd /d "%~dp0"
if not exist "My-PC.connection.json" (
  echo My-PC.connection.json missing. Supply your PRIVATE connection file first.
  pause
  exit /b 1
)
start /wait "" "QRPrintInbox-Kurulum.exe" /install
if errorlevel 1 goto failed
set "INBOX_EXE=%LOCALAPPDATA%\Programs\QRPrintInbox\QRPrintInbox.exe"
start /wait "" "%INBOX_EXE%" /import "%~dp0My-PC.connection.json"
if errorlevel 1 goto failed
start /wait "" "%INBOX_EXE%" /start
if errorlevel 1 goto failed
start "" "%INBOX_EXE%"
exit /b 0
:failed
echo Setup failed. Check .NET 4.8, disk access and your connection JSON.
pause
exit /b 1
