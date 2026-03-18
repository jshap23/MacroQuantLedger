@echo off
title MacroQuant Ledger
cd /d "%~dp0"

echo Checking for existing instance on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080 "') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting MacroQuant Ledger...
call C:\Users\jshap\anaconda3\Scripts\activate.bat C:\Users\jshap\anaconda3
call conda activate mqledger
python app.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: App failed to start. See message above.
    pause
)
