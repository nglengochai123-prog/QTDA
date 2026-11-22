@echo off
rem Task Scheduler goi moi sang va khi dang nhap: noi them cac ngay mo phong con thieu toi hom nay vao db.sqlite3.
rem Chi dung cho co so du lieu mo phong (tai khoan demo_*); lenh tu bo qua neu da du hoac khong phai bo mo phong.
cd /d "%~dp0.."
if not exist logs mkdir logs
".venv\Scripts\python.exe" manage.py tao_du_lieu_mo_phong --noi-them >> logs\noi_mo_phong.log 2>&1
