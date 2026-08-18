@echo off
title Kick Views Bot - Setup
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ╔══════════════════════════════════════╗
echo ║     Kick Views Bot - Setup           ║
echo ╚══════════════════════════════════════╝
echo.

:: ─── Check Python ───
echo [1/5] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python not found! Downloading Python 3.12...
    echo.

    powershell -Command "& {$url='https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe'; $out='%TEMP%\python_installer.exe'; Write-Host 'Downloading Python...'; (New-Object Net.WebClient).DownloadFile($url,$out); Write-Host 'Installing Python (this may take a minute)...'; Start-Process $out -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0' -Wait; Remove-Item $out -Force; Write-Host 'Python installed!'}"

    :: Refresh PATH
    set "PATH=%PATH%;C:\Program Files\Python312;C:\Program Files\Python312\Scripts"

    python --version >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ❌ Python install failed or PATH not updated.
        echo Please install Python 3.12+ manually from https://python.org
        echo Make sure to check "Add Python to PATH" during install!
        pause
        exit /b 1
    )
)

python --version
echo ✅ Python found!
echo.

:: ─── Install packages ───
echo [2/5] Installing Python packages...
echo.
python -m pip install --upgrade pip >nul 2>&1
python -m pip install discord.py curl_cffi
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Failed to install packages!
    pause
    exit /b 1
)
echo ✅ Packages installed!
echo.

:: ─── Create config.json if missing ───
echo [3/5] Checking config.json...
if not exist "config.json" (
    if exist "config.example.json" (
        copy "config.example.json" "config.json" >nul
        echo.
        echo ⚠️  config.json created from template!
        echo    Open config.json and paste your bot token in "bot_token"
        echo.
        start notepad config.json
        pause
    ) else (
        echo ❌ No config.example.json found!
    )
) else (
    echo ✅ config.json exists!
)
echo.

:: ─── Create start.bat ───
echo [4/5] Creating start.bat...
(
echo @echo off
echo title Kick Views Bot
echo chcp 65001 ^>nul 2^^^&1
echo cd /d "%%~dp0"
echo echo Starting bots...
echo start "BotMain" /min cmd /c "python -u bot.py ^>^> bot_run.log 2^>^> bot_err.log"
echo start "BotTest" /min cmd /c "python -u TEST.py ^>^> test_run.log 2^>^> test_err.log"
echo echo Both bots started!
echo timeout /t 3 ^>nul
) > start.bat
echo ✅ start.bat created!
echo.

:: ─── Create stop.bat ───
echo [5/5] Creating stop.bat...
(
echo @echo off
echo echo Stopping bots...
echo taskkill /F /FI "WINDOWTITLE eq BotMain*" ^>nul 2^^^&1
echo taskkill /F /FI "WINDOWTITLE eq BotTest*" ^>nul 2^^^&1
echo echo Done!
echo timeout /t 2 ^>nul
) > stop.bat
echo ✅ stop.bat created!
echo.

echo ╔══════════════════════════════════════╗
echo ║           Setup Complete!            ║
echo ╠══════════════════════════════════════╣
echo ║  1. Edit config.json with your token ║
echo ║  2. Run start.bat to launch bots     ║
echo ║  3. Run stop.bat to stop bots        ║
echo ╚══════════════════════════════════════╝
echo.
pause
