@echo off
chcp 65001 >nul
title Book Library - LAN Share Setup
echo ============================================================
echo  Right-click - Run as Administrator
echo ============================================================
echo.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Right-click this file and select "Run as administrator".
    pause
    exit /b 1
)

echo [1/4] Creating LAN folder share...
net share booklib=D:\Pcode\play\_skills\book-library-skill /grant:Everyone,FULL /remark:"Book Library OCR"
if %errorlevel% equ 0 (
    echo   OK - Share: \\192.168.1.171\booklib
) else (
    echo   WARN: net share failed. Trying existing shares...
)
echo.

echo [2/4] Opening firewall for file sharing (private)...
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes profile=private 2>nul
echo   Done.
echo.

echo [3/4] Adding notebook to WinRM TrustedHosts...
powershell -Command "Set-Item WSMan:\localhost\Client\TrustedHosts -Value '192.168.1.186' -Concatenate -Force" 2>nul
echo   Done.
echo.

echo [4/4] Enabling remote admin token...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f >nul 2>&1
echo   Done.
echo.
echo ============================================================
echo COMPLETE! Share path: \\%COMPUTERNAME%\booklib
echo Run notebook scripts on the laptop now.
echo ============================================================
pause
