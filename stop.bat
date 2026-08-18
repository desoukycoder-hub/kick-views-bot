@echo off
echo Stopping bots...
taskkill /F /FI "WINDOWTITLE eq BotMain*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq BotTest*" >nul 2>&1
echo Done!
timeout /t 2 >nul
