@echo off
REM Creates reminder notifications (overdue complaints, late lab work). Schedule daily at 07:00.
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
python manage.py send_reminders
