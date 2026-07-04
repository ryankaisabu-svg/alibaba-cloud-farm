@echo off
REM Qwen Cloud Farm - Modern GUI Launcher
REM ======================================
cd /d "%~dp0"
echo Starting Qwen Cloud Farm GUI...
"C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe" qwen_farm_gui.py
if errorlevel 1 (
    echo.
    echo ERROR: GUI failed to start. Make sure all dependencies are installed:
    echo pip install customtkinter packaging python-dotenv
    echo.
)
pause
