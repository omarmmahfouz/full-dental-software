@echo off
REM The nightly backup. Schedule it every night with the Task Scheduler (e.g. at 2 am):
REM   1. PostgreSQL's copy of the database (or the SQLite file) into backups\YYYY-MM-DD, kept 30 days (small).
REM   2. The system's backup: a ZIP of all the data (in data\backups, the newest 10 are kept), then a copy of
REM      the NEW and CHANGED photos and files only, to FILES_BACKUP_DIR. Set it in .env to a folder on another
REM      disk, e.g.  FILES_BACKUP_DIR=E:\CIA backup\files   (nothing is ever deleted there).
REM   3. The small previews of any photo that has none yet.
REM Settings -> Backup, and the owner's home page, show whether the last backup worked.
REM For PostgreSQL, pg_dump.exe must be on PATH (e.g. C:\Program Files\PostgreSQL\16\bin)
REM and the password in the PGPASSWORD variable below (same as DB_PASSWORD in .env).
cd /d "%~dp0\..\.."
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set TARGET=backups\%TODAY%
mkdir "%TARGET%" 2>nul
set PGPASSWORD=change-me-too
pg_dump -h localhost -U dental -Fc -f "%TARGET%\dental.dump" dental || echo pg_dump failed or not used (SQLite)
if exist data\db.sqlite3 copy /y data\db.sqlite3 "%TARGET%\db.sqlite3" >nul
call .venv\Scripts\activate.bat
python manage.py backup || echo The backup of the system failed: open Settings - Backup to see why.
python manage.py make_previews >nul
REM Keep 30 days of database copies (the photo copy is never deleted).
forfiles /p backups /d -30 /c "cmd /c if @isdir==TRUE rmdir /s /q @path" 2>nul
echo Backup done.
