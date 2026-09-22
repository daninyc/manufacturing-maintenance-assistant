@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoExit -ExecutionPolicy Bypass -Command ". './scripts/app_env.ps1'; Set-Location 'D:/CodexWorkspace/maintenance-client-dev'; Write-Host 'App environment loaded. Run: flutter doctor -v'"
