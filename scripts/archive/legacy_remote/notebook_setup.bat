@echo off
chcp 65001 >nul
echo ============================================================
echo  Notebook Environment Setup for Book Library OCR
echo ============================================================
echo.

REM === 1. Map network drive ===
echo [1/4] Mapping network drive Z: to \\192.168.1.171\booklib ...
net use Z: \\192.168.1.171\booklib /persistent:no >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Cannot map network drive.
    pause
    exit /b 1
)
echo   OK
echo.

REM === 2. Check Python ===
echo [2/4] Checking Python...
where python >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('python --version') do echo   Found: %%v
    set PYCMD=python
    goto :check_pip
)
where py >nul 2>&1
if %errorlevel% equ 0 (
    echo   Found Python Launcher
    set PYCMD=py -3
    goto :check_pip
)
echo   Python not found. Installing via winget...
winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo ERROR: winget install failed.
    pause
    exit /b 1
)
set PYCMD=py -3
echo.

:check_pip
REM === 3. Install dependencies ===
echo [3/4] Installing Python dependencies...
%PYCMD% -m pip install --upgrade pip wheel
%PYCMD% -m pip install rapidocr_onnxruntime pymupdf pdf2image pillow
if %errorlevel% neq 0 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)
echo   Done
echo.

REM === 4. Install Poppler ===
echo [4/4] Checking Poppler...
where pdftoppm >nul 2>&1
if %errorlevel% equ 0 goto :done
where poppler >nul 2>&1
if %errorlevel% equ 0 goto :done
echo   Installing Poppler...
winget install oschwartz10612.Poppler --accept-source-agreements --accept-package-agreements
echo.

:done
echo ============================================================
echo  Setup Complete!
echo ============================================================
echo Run notebook_shard3.bat and notebook_shard4.bat in two windows.
pause
