@echo off
REM One-time installation on a Windows clinic server (no Docker).
REM Requirements: Python 3.12 (tick "Add to PATH") and PostgreSQL 16 (or use SQLite for a trial).
REM Run this file from the project folder:  deploy\windows\install.bat
cd /d "%~dp0\..\.."
if not exist .env (
  copy .env.example .env
  echo.
  echo  ==> Edit the new .env file ^(secret key, server IP, database password^) and run this again.
  notepad .env
  exit /b 1
)
python -m venv .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :error
python manage.py migrate || goto :error
python manage.py setup_clinic || goto :error
python manage.py organize_photos || goto :error
python manage.py collectstatic --noinput || goto :error
echo.
echo  ==> Create the owner account (manager login):
python manage.py createsuperuser
echo.
echo  Installation finished. Start the system with deploy\windows\start_server.bat
exit /b 0
:error
echo Installation failed. Read the message above.
exit /b 1
