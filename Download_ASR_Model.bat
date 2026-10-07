@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv_asr\Scripts\python.exe Download_ASR_Model.py
if errorlevel 1 echo Model provisioning failed. Do not start transcription.
pause
