@echo off
cd /d "%~dp0"
echo Killing all bots...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /v /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /i "bot.py TEST.py" >nul && taskkill /F /PID %%a >nul 2>&1
)
echo Done!
