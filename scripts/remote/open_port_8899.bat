@echo off
chcp 65001 >nul
title Open Port 8899 for LAN
echo ============================================================
echo  Open TCP port 8899 for LAN (192.168.1.0/24)
echo ============================================================
echo.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click and select "Run as administrator".
    pause
    exit /b 1
)

netsh advfirewall firewall add rule name="BookLib_OCR_8899" dir=in action=allow protocol=TCP localport=8899 remoteip=192.168.1.0/24 profile=private

echo.
echo ============================================================
echo  Port 8899 opened!
echo  Test from laptop: curl http://192.168.1.171:8899/api/ping
echo ============================================================
pause
