@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 Check_ASR_Environment.py
pause
