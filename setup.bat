@echo off
title Kick Views Bot - Setup
cd /d "%~dp0"

echo ========================================
echo     Kick Views Bot - Setup
echo ========================================
echo.

echo [1/3] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python not found! Downloading Python 3.12...
    echo.
    powershell -Command "& {$url='https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe'; $out='%TEMP%\python_installer.exe'; Write-Host 'Downloading Python...'; (New-Object Net.WebClient).DownloadFile($url,$out); Write-Host 'Installing Python...'; Start-Process $out -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0' -Wait; Remove-Item $out -Force; Write-Host 'Python installed!'}"
    set "PATH=%PATH%;C:\Program Files\Python312;C:\Program Files\Python312\Scripts"
    python --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: Python install failed.
        echo Please install Python 3.12+ from https://python.org
        echo Make sure to check "Add Python to PATH" during install!
        pause
        exit /b 1
    )
)
python --version
echo [OK] Python found!
echo.

echo [2/3] Installing packages...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install discord.py curl_cffi
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install packages!
    pause
    exit /b 1
)
echo [OK] Packages installed!
echo.

echo [3/3] Checking config.json...
if not exist "config.json" (
    if exist "config.example.json" (
        copy "config.example.json" "config.json" >nul
        echo.
        echo config.json created from template!
        echo Open config.json and paste your bot token in "bot_token"
        echo.
        start notepad config.json
        pause
    ) else (
        echo ERROR: No config.example.json found!
    )
) else (
    echo [OK] config.json exists!
)
echo.

echo ========================================
echo           Setup Complete!
echo ========================================
echo.
echo   1. Make sure config.json has your token
echo   2. Run start.bat to launch bots
echo   3. Run stop.bat to stop bots
echo.
pause
