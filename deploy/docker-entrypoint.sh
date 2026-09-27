#!/bin/sh
# Prepare the database, then start the web server.
set -e
python manage.py migrate --noinput
python manage.py setup_clinic
python manage.py organize_photos
# WEB_WORKERS x WEB_THREADS pages can be made at the same time (4 x 4 = 16 by default; see docs/deployment.md).
# Each worker is renewed after a few thousand pages, so memory stays low over months.
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
    --workers "${WEB_WORKERS:-4}" --threads "${WEB_THREADS:-4}" --timeout 120 \
    --max-requests 3000 --max-requests-jitter 300 --access-logfile -
