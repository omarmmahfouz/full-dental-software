@echo off
REM ============================================================
REM  THE PAPER READER on a Windows PC with the internet: double-click this file.
REM  Needs Python 3.12 or newer from python.org ("Add python.exe to PATH" ticked).
REM  The first time it prepares itself, then opens the reader in the browser:
REM  make the login of the person in charge, then bring in the lists from the dental system.
REM  Close this window to stop the reader.
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
  echo  First run: preparing the Paper Reader, this takes a few minutes...
  %PY% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

if not exist .env python -c "import secrets; open('.env', 'w', encoding='utf-8').write('# The Paper Reader settings, made on the first run. Add the key to Claude below.\nREADER_SECRET_KEY=' + secrets.token_urlsafe(50) + '\nREADER_ALLOWED_HOSTS=*\n# ANTHROPIC_API_KEY=sk-ant-...\n')" || goto :error

python manage.py migrate --verbosity 0 || goto :error
python manage.py collectstatic --noinput --verbosity 0 || goto :error

set "LANIP=this-PC-IP"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do set "LANIP=%%a"
set "LANIP=%LANIP: =%"
echo.
echo  ============================================================
echo   The Paper Reader is running.   Open:  http://localhost:8100
echo   From the reception PCs on the same network:  http://%LANIP%:8100
echo   Close this window to stop it.
echo  ============================================================
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8100"
waitress-serve --listen=0.0.0.0:8100 --threads=8 site_config.wsgi:application
exit /b 0

:error
echo.
echo  Something went wrong - read the message above.
pause
exit /b 1
