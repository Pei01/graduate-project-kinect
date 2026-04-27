@echo off
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    echo [kinect] Activating venv...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo [kinect] Activating .venv...
    call .venv\Scripts\activate.bat
) else (
    echo [kinect] No venv found, using system python.
)

python main.py
pause
