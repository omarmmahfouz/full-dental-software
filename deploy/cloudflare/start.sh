#!/bin/sh
# Starts the online demo inside its Cloudflare container. The data is in a Supabase database, so it is kept when
# the container sleeps; uploaded photos are on the container's own disk and are lost when it sleeps.
set -e
cd /app

# Supabase's pooler has two addresses per region and a project answers on one of them: use the first that works.
DB_HOST=$(python deploy/cloudflare/demo_setup.py host)
export DB_HOST
echo "Database: $DB_HOST"

python manage.py migrate --noinput

if python deploy/cloudflare/demo_setup.py is-empty; then
  # The first start: the lists, rooms and places, then the sample data, all in one go (several minutes).
  python deploy/cloudflare/demo_setup.py fill
else
  # Later starts: the lists of a newer version are added while the pages already open.
  (python manage.py setup_clinic > /dev/null 2>&1 || echo "setup_clinic failed") &
fi

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
    --workers "${WEB_WORKERS:-2}" --threads "${WEB_THREADS:-4}" --timeout 120 \
    --max-requests 3000 --max-requests-jitter 300 --access-logfile -
