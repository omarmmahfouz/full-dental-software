@echo off
REM Keep the photos, X-rays and scans in another folder (e.g. a bigger disk). Round 15.
REM Copies every file to the new folder, checks each copy, then writes MEDIA_ROOT in .env.
REM Close the system (start_server.bat) after it ends and start it again: new photos go to the new folder.
REM The old folder is NOT deleted: delete it yourself after checking a few patients' photos.
chcp 65001 >nul
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
set /p NEWDIR=The new folder for the photos (e.g. D:\CIA photos): 
if "%NEWDIR%"=="" goto :end
python manage.py move_photos "%NEWDIR%"
:end
pause
