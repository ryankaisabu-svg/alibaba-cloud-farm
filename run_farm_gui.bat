@echo off
REM ============================================
REM  Farm GUI — Standalone Launcher
REM  Auto-detects Python with Playwright installed
REM ============================================
cd /d "%~dp0"

REM Try Python 3.13 first (has playwright + patchright)
set "PY313=C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe"
if exist "%PY313%" (
    "%PY313%" -c "import playwright" 2>nul && (
        echo [OK] Using Python 3.13 with Playwright
        "%PY313%" -m gui.app
        goto end
    )
)

REM Try system python
python -c "import playwright" 2>nul && (
    echo [OK] Using system Python with Playwright
    python -m gui.app
    goto end
)

REM Try py launcher
py -3.13 -c "import playwright" 2>nul && (
    echo [OK] Using py 3.13 with Playwright
    py -3.13 -m gui.app
    goto end
)

REM Not found
echo [ERROR] Playwright not found in any Python installation!
echo.
echo Install with:
echo   pip install playwright
echo   playwright install chromium
echo.
pause
exit /b 1

:end
pause
