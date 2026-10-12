@echo off
cd /d "C:\devops\daily-batch-pipeline"
if not exist logs mkdir logs
.venv\Scripts\python.exe -m src.main --incremental >> logs\scheduler.log 2>&1
exit /b %ERRORLEVEL%
