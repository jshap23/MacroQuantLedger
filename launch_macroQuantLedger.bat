@echo off
title MacroQuant Ledger
cd /d "%~dp0"
echo Starting MacroQuant Ledger...
call C:\Users\jshap\anaconda3\Scripts\activate.bat C:\Users\jshap\anaconda3
call conda activate mqledger
python app.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: App failed to start. See message above.
    pause
)
