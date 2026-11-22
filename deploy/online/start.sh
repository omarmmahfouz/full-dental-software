#!/bin/sh
# Starts the online demo (deploy/online/README.md). The data is in the Supabase project "cia-dental-demo", so it is
# kept when the server sleeps; uploaded photos are on the server's own disk and are lost when it sleeps.
set -e
cd /app

# The settings of the online demo, unless the host gives others: only DB_PASSWORD and DEMO_PASSWORD must be set.
: "${DB_ENGINE:=postgres}" "${DB_NAME:=postgres}" "${DB_PORT:=5432}"
: "${DB_USER:=dental_demo.hhlvopauzprdsryleodu}"
: "${DB_HOSTS:=aws-1-eu-central-1.pooler.supabase.com,aws-0-eu-central-1.pooler.supabase.com}"
: "${DJANGO_ALLOWED_HOSTS:=*}" "${DJANGO_HTTPS:=1}" "${DJANGO_SSL_REDIRECT:=0}"
: "${DJANGO_CSRF_TRUSTED_ORIGINS:=https://*.koyeb.app,https://*.workers.dev,https://*.onrender.com}"
# Behind the host's HTTPS front: every network may open it (the logins and passwords still apply).
: "${ALLOWED_NETWORKS:=*}" "${TRUSTED_PROXIES:=0.0.0.0/0,::/0}"
: "${WEB_WORKERS:=1}" "${WEB_THREADS:=8}" "${PORT:=8000}"
export DB_ENGINE DB_NAME DB_PORT DB_USER DB_HOSTS DJANGO_ALLOWED_HOSTS DJANGO_HTTPS DJANGO_SSL_REDIRECT \
    DJANGO_CSRF_TRUSTED_ORIGINS ALLOWED_NETWORKS TRUSTED_PROXIES WEB_WORKERS WEB_THREADS PORT
if [ -z "$DB_PASSWORD" ] || [ -z "$DEMO_PASSWORD" ]; then
  echo "Set DB_PASSWORD and DEMO_PASSWORD in the host's settings (deploy/online/README.md)." >&2
  exit 1
fi
if [ -z "$DJANGO_SECRET_KEY" ]; then
  # The same key at every start (logins stay open after a sleep), made from a secret the host already has.
  DJANGO_SECRET_KEY=$(python -c "import hashlib, os; print(hashlib.sha256(('cia-demo-key:' + os.environ['DB_PASSWORD']).encode()).hexdigest())")
  export DJANGO_SECRET_KEY
fi

# A "starting" page answers on the port at once: the host sees the server alive while the database is prepared
# (the first start fills the sample data, several minutes on a small server).
python deploy/online/demo_setup.py wait-page &
WAIT_PAGE=$!
stop_wait_page() { kill "$WAIT_PAGE" 2>/dev/null || true; wait "$WAIT_PAGE" 2>/dev/null || true; }
trap stop_wait_page EXIT

# One step, one start of Django: the database address of DB_HOSTS that answers (Supabase's pooler has two per
# region), migrate, then the sample data on an empty database or a newer version's lists after an update.
DB_HOST_FILE=/tmp/db_host python deploy/online/demo_setup.py prepare
DB_HOST=$(cat /tmp/db_host)
export DB_HOST

stop_wait_page
trap - EXIT
# --preload: the system is loaded once, then shared by the workers (quicker on a small server).
exec gunicorn config.wsgi:application --preload --bind "0.0.0.0:$PORT" \
    --workers "$WEB_WORKERS" --threads "$WEB_THREADS" --timeout 120 \
    --max-requests 3000 --max-requests-jitter 300 --access-logfile -
