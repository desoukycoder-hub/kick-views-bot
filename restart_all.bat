@echo off
cd /d "%~dp0"
echo Killing old bots...
taskkill /F /FI "WINDOWTITLE eq BotMain*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq BotTest*" /T >nul 2>&1
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /v /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /i "bot.py TEST.py" >nul && taskkill /F /PID %%a >nul 2>&1
)
echo Done killing.
timeout /t 2 >nul
echo Starting bots...
start "BotMain" /min cmd /c "python -u bot.py >> bot_run.log 2>> bot_err.log"
start "BotTest" /min cmd /c "python -u TEST.py >> test_run.log 2>> test_err.log"
echo Both bots started!
timeout /t 5 >nul
