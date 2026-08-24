@echo off
title MacroQuant Ledger
cd /d "%~dp0"

echo Checking for existing instance on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080 "') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting MacroQuant Ledger...
call C:\Users\jshap\miniforge3\Scripts\activate.bat mqledger

start "MacroQuant Ledger Server" /min python app.py

echo Waiting for server to start...
timeout /t 3 /nobreak >nul

echo Opening Microsoft Edge...
start "" "microsoft-edge:http://localhost:8080"
