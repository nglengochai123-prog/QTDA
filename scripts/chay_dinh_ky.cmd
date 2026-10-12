@echo off
rem Task Scheduler goi moi phut: chuyen cap, giao cham, nhac, canh bao, thong bao day. Nhat ky: logs\dinh_ky.log
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" manage.py chay_dinh_ky >> logs\dinh_ky.log 2>&1
