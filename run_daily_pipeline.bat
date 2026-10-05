@echo off
cd /d C:\devops\daily-batch-pipeline
.venv\Scripts\python.exe -m src.main >> logs\scheduler.log 2>&1
exit /b %ERRORLEVEL%
