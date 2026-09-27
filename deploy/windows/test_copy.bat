@echo off
REM A TEST COPY of the system with today's data, on port 8001: try a new version or a big change there first.
REM Every page of it shows a yellow TEST COPY banner; nothing done in it changes the real system.
REM The photos are not copied (they stay in the real system only).
REM Open it from any PC: http://<server-ip>:8001/  (allow port 8001 in the Windows Firewall, private networks only).
REM Close this window to stop it. Running this again makes a fresh copy with the data of that day.
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
python manage.py make_test_copy --serve 8001
