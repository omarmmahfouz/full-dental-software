@echo off
REM ============================================================
REM  TRIAL on a Windows PC: double-click this file.
REM  Needs Python 3.12 or newer from python.org ("Add python.exe to PATH" ticked).
REM  Creates a practice database with sample data, starts the system
REM  and opens it in the browser. Close this window to stop it.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo.
  echo  Python is not installed. Install it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during installation, then run this file again.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo  First run: preparing the system, this takes a few minutes...
  %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

if not exist .env (
  >.env echo # Trial settings created by trial-windows.bat - NOT for the real clinic server
  >>.env echo DJANGO_DEBUG=1
  >>.env echo DB_ENGINE=sqlite
  >>.env echo DJANGO_ALLOWED_HOSTS=*
)

python manage.py migrate --verbosity 0 || goto :error
python manage.py setup_clinic >nul || goto :error
python manage.py load_demo_data --password demo12345 --if-empty || goto :error
python manage.py organize_photos >nul || goto :error

set "LANIP=this-PC-IP"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do set "LANIP=%%a"
set "LANIP=%LANIP: =%"
echo.
echo  ============================================================
echo   The system is running.   Open:  http://localhost:8000
echo   From other PCs / tablets on the same network:  http://%LANIP%:8000
echo.
echo   Users (password demo12345):  owner  headcia  teamhead  dentist1  dentist2  secretary  secretary2  stock
echo   Close this window to stop the system.
echo  ============================================================
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
python manage.py runserver 0.0.0.0:8000
exit /b 0

:error
echo.
echo  Something went wrong - read the message above.
pause
exit /b 1
