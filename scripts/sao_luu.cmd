@echo off
rem Task Scheduler goi moi ngay: sao luu ra LAM_BACKUP_DIR, giu LAM_BACKUP_KEEP ban. Nhat ky: logs\sao_luu.log
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ==== %DATE% %TIME% >> logs\sao_luu.log
".venv\Scripts\python.exe" manage.py sao_luu >> logs\sao_luu.log 2>&1
exit /b %ERRORLEVEL%
