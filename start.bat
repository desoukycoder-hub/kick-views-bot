@echo off
title Kick Views Bot
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo Starting bots...
start "BotMain" /min cmd /c "python -u bot.py >> bot_run.log 2>> bot_err.log"
start "BotTest" /min cmd /c "python -u TEST.py >> test_run.log 2>> test_err.log"
echo Both bots started!
timeout /t 3 >nul
