@echo off
rem start_remote.cmd — runs Kaizumi with the Bluetooth phone transport enabled.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -u main.py --remote
) else (
  python -u main.py --remote
)