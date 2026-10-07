@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv_asr\Scripts\python.exe Probe_ASR.py
pause
