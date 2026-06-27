@echo off
REM ============================================
REM  Qwen Cloud Farm — Standalone Launcher
REM  Usage: run_qwen.bat [count] [show] [debug]
REM    count  = number of accounts (default: 5)
REM    show   = show browser 1/0 (default: 1)
REM    debug  = debug screenshots 1/0 (default: 1)
REM  Examples:
REM    run_qwen.bat 5 1 1    (5 accounts, show, debug)
REM    run_qwen.bat 10 0 0   (10 accounts, headless, no debug)
REM ============================================

setlocal

set COUNT=%1
if "%COUNT%"=="" set COUNT=5
set SHOW=%2
if "%SHOW%"=="" set SHOW=1
set DEBUG=%3
if "%DEBUG%"=="" set DEBUG=1

set PYTHON=C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe
set DIR=E:\WEB\alibaba-cloud-farm

cd /d %DIR%

set FLAGS=--count %COUNT%
if "%SHOW%"=="1" set FLAGS=%FLAGS% --show
if "%DEBUG%"=="1" set FLAGS=%FLAGS% --debug

echo.
echo ========================================
echo  Qwen Cloud Farm — %COUNT% account(s)
echo  Flags: %FLAGS%
echo ========================================
echo.

%PYTHON% alibaba_farm.py %FLAGS%

echo.
echo ========================================
echo  Done! %COUNT% account(s) processed.
echo  Results: %DIR%\qwen_results.json
echo  CSV:     %DIR%\qwen_accounts.csv
echo ========================================
pause
