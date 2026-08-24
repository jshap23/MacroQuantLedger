@echo off
title MacroQuant Ledger
cd /d "%~dp0"

echo Starting MacroQuant Ledger...
call C:\Users\jshap\miniforge3\Scripts\activate.bat mqledger

start "" pythonw "launch.py"
