@echo off
chcp 65001 >nul
title Enable SMB File Sharing for LAN
echo ============================================================
echo  Enable SMB File Sharing for 192.168.1.0/24
echo ============================================================
echo.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click and select "Run as administrator".
    pause
    exit /b 1
)

echo [1/3] Enabling SMB firewall rules for Private profile...
netsh advfirewall firewall set rule group="文件和打印机共享" new enable=Yes profile=private
echo   Done.
echo.

echo [2/3] Setting NTFS permission on project folder...
icacls "%~dp0..\..\data" /grant "Everyone:(OI)(CI)RX" /T 2>nul
echo   Done.
echo.

echo [3/3] Verifying D$ share...
net share D$ >nul 2>&1
if %errorlevel% equ 0 (
    echo   D$ share is active.
) else (
    echo   WARNING: D$ share not found.
)
echo.
echo ============================================================
echo  DONE! Notebook can now access:
echo    \\192.168.1.171\D$\Pcode\play\_skills\book-library-skill
echo ============================================================
pause
