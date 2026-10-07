@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv_asr\Scripts\python.exe" py -3.10 -m venv .venv_asr
if errorlevel 1 goto failed
.venv_asr\Scripts\python.exe -m pip install --only-binary=:all: -r asr_requirements.txt
if errorlevel 1 goto failed
.venv_asr\Scripts\python.exe -m pip check
if errorlevel 1 goto failed
.venv_asr\Scripts\python.exe -m pip freeze > ASR_INSTALLED_LOCK.txt
if errorlevel 1 goto failed
echo ASR Python packages are installed. Download the model next.
pause
exit /b 0
:failed
echo Setup failed. Do not start transcription. Send the error text.
pause
exit /b 1
