@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.customer_acceptance_checks --suite offline
pause
