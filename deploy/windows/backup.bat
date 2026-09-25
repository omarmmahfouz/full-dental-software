@echo off
REM Daily backup: database + uploaded files (ID scans, invoices) into backups\YYYY-MM-DD.
REM Schedule it daily with Task Scheduler, and copy the "backups" folder to an external disk weekly.
REM For PostgreSQL, pg_dump.exe must be on PATH (e.g. C:\Program Files\PostgreSQL\16\bin)
REM and the password in the PGPASSWORD variable below (same as DB_PASSWORD in .env).
cd /d "%~dp0\..\.."
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set TARGET=backups\%TODAY%
mkdir "%TARGET%" 2>nul
set PGPASSWORD=change-me-too
pg_dump -h localhost -U dental -Fc -f "%TARGET%\dental.dump" dental || echo pg_dump failed or not used (SQLite)
if exist data\db.sqlite3 copy /y data\db.sqlite3 "%TARGET%\db.sqlite3" >nul
robocopy data\media "%TARGET%\media" /E /NFL /NDL /NJH /NJS >nul
REM The system's own full backup too: all data as JSON, Excel and CSV plus the files (data\backups).
call .venv\Scripts\activate.bat
python manage.py backup || echo The full backup of the system failed
REM Keep 30 days of backups.
forfiles /p backups /d -30 /c "cmd /c if @isdir==TRUE rmdir /s /q @path" 2>nul
echo Backup saved in %TARGET%
