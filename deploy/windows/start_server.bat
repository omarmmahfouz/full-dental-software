@echo off
REM Starts the system on port 80 so staff open http://<server-ip>/ from any PC on the clinic network.
REM To start automatically: Task Scheduler -> Create Task -> "At startup" -> run this file
REM ("Run whether user is logged on or not", "Run with highest privileges").
cd /d "%~dp0\..\.."
call .venv\Scripts\activate.bat
waitress-serve --listen=*:80 --threads=8 config.wsgi:application
