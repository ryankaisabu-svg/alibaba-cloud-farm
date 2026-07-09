@echo off
REM ============================================
REM  Force Restart Farm GUI
REM  Kills old Python GUI processes and starts fresh
REM ============================================
echo [*] Killing old GUI processes...
taskkill /F /IM python.exe /FI "MEMUSAGE gt 50000" 2>nul
timeout /t 2 /nobreak >nul

echo [*] Starting fresh GUI...
cd /d "%~dp0"
call run_farm_gui.bat
