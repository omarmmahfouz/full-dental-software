@echo off
REM Update to a new version, safely. Run it from the project folder:  deploy\windows\update.bat
REM   1. A backup of all the data is made first. If it fails, nothing is changed.
REM   2. The new version is taken from GitHub (git pull).
REM   3. The new packages, the database changes and the new list items are applied.
REM Then restart the server. Tip: try a new version on the test copy first (test_copy.bat).
REM Without git (the folder was copied by hand): make a backup from Settings - Backup FIRST, then copy the
REM new files over the folder, then run install.bat.
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
if not exist .git (
  echo This folder was not taken from GitHub: make a backup from Settings - Backup, copy the new files over it,
  echo then run deploy\windows\install.bat.
  exit /b 1
)
python manage.py backup --no-files || goto :nobackup
for /f %%i in ('git rev-parse HEAD') do set BEFORE=%%i
git pull || goto :error
python -m pip install -r requirements.txt || goto :error
python manage.py migrate || goto :error
python manage.py setup_clinic || goto :error
python manage.py collectstatic --noinput || goto :error
echo.
echo  Update done. Restart the server (start_server.bat, or restart the computer).
echo  If something is wrong with the new version, go back to the old one with:
echo    git checkout %BEFORE%
echo  and put back the data of before the update with the newest backup in data\backups:
echo    python manage.py restore_backup "data\backups\backup_....zip"
exit /b 0
:nobackup
echo The backup failed, so nothing was updated. Open Settings - Backup to see why.
exit /b 1
:error
echo The update stopped. The data is safe in the backup made at the start (data\backups).
echo To go back to the old version:  git checkout %BEFORE%
exit /b 1
