@echo off
cd /d %~dp0
python tender_bot.py --loop 30
pause
