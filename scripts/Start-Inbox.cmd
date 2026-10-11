@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m scripts.manage start
if errorlevel 1 pause
