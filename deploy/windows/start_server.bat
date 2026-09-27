@echo off
REM Starts the system on port 80 so staff open http://<server-ip>/ from any PC on the clinic network.
REM To start automatically: Task Scheduler -> Create Task -> "At startup" -> run this file
REM ("Run whether user is logged on or not", "Run with highest privileges").
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
REM Up to 16 pages are made at the same time. For a busy clinic, set a higher WEB_THREADS (e.g. 24) here.
if "%WEB_THREADS%"=="" set WEB_THREADS=16
waitress-serve --listen=*:80 --threads=%WEB_THREADS% --connection-limit=500 config.wsgi:application
