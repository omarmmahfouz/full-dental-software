#!/bin/sh
# Prepare the database, then start the web server.
set -e
python manage.py migrate --noinput
python manage.py setup_clinic
python manage.py organize_photos
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120 --access-logfile -
