@echo off
chcp 65001 >nul
echo [Notebook] Shard 3 - HTTP OCR Worker
echo.

where py >nul 2>&1 && set PYCMD=py -3
if not defined PYCMD (
    where python >nul 2>&1 && set PYCMD=python
)
if not defined PYCMD (
    echo ERROR: Python not found. Run notebook_setup.bat first.
    pause
    exit /b 1
)

cd /d %~dp0..\..\..

%PYCMD% scripts\remote\notebook_http_worker.py --shard 3 --host 192.168.1.171 --port 8899

echo.
echo [Notebook] Shard 3 finished!
pause
