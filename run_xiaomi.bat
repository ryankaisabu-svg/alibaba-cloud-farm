@echo off
REM ============================================
REM  Xiaomi MiMo Farm — Standalone Launcher
REM  Usage: run_xiaomi.bat [count] [show] [auto_captcha]
REM    count         = number of accounts (default: 1)
REM    show          = show browser 1/0 (default: 1)
REM    auto_captcha  = auto-solve CAPTCHA 1/0 (default: 0)
REM  Examples:
REM    run_xiaomi.bat 1 1 0    (1 account, show, manual captcha)
REM    run_xiaomi.bat 5 1 1    (5 accounts, show, auto captcha via CapSolver)
REM    run_xiaomi.bat 5 0 1    (5 accounts, headless, auto captcha)
REM ============================================

setlocal

set COUNT=%1
if "%COUNT%"=="" set COUNT=1
set SHOW=%2
if "%SHOW%"=="" set SHOW=1
set AUTO=%3
if "%AUTO%"=="" set AUTO=0

set PYTHON=C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe
set DIR=E:\WEB\alibaba-cloud-farm

cd /d %DIR%

set FLAGS=--provider gmail --debug
if "%SHOW%"=="1" set FLAGS=%FLAGS% --show
if "%AUTO%"=="1" set FLAGS=%FLAGS% --auto-captcha

for /l %%i in (1,1,%COUNT%) do (
    echo.
    echo ========================================
    echo  Creating Xiaomi MiMo Account %%i of %COUNT%
    echo ========================================
    %PYTHON% xiaomi_farm.py %FLAGS%
    if %%i lss %COUNT% (
        echo Waiting 10s before next account...
        timeout /t 10 /nobreak >nul
    )
)

echo.
echo ========================================
echo  Done! %COUNT% account(s) processed.
echo  Results: %DIR%\xiaomi_results.json
echo  CSV:     %DIR%\xiaomi_accounts.csv
echo ========================================
pause
