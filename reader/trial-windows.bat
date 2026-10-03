@echo off
REM ============================================================
REM  A PRACTICE Paper Reader with sample files: double-click this file.
REM  Nothing is sent to Claude (no key needed). Its data is in "data-trial",
REM  apart from the real reader. Close this window to stop it.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo  Python is not installed. Install it from https://www.python.org/downloads/ then run this file again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo  First run: preparing the Paper Reader, this takes a few minutes...
  %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

set "READER_DEBUG=1"
set "READER_DATA_DIR=%~dp0data-trial"
set "READER_ALLOWED_HOSTS=*"
set "ANTHROPIC_API_KEY="
set "FRESH="
if not exist "%READER_DATA_DIR%\reader.sqlite3" set "FRESH=1"
python manage.py migrate --verbosity 0 || goto :error
if defined FRESH python manage.py load_reader_demo --password demo12345 || goto :error

echo.
echo  ============================================================
echo   The PRACTICE Paper Reader is running:  http://localhost:8100
echo   Logins (password demo12345):  owner (the person in charge)  secretary
echo   Close this window to stop it.
echo  ============================================================
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8100"
python manage.py runserver 0.0.0.0:8100 --noreload
exit /b 0

:error
echo.
echo  Something went wrong - read the message above.
pause
exit /b 1
