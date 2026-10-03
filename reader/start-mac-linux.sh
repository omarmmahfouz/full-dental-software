#!/bin/sh
# THE PAPER READER on a Mac or Linux PC with the internet:  sh start-mac-linux.sh
# Prepares itself the first time and starts the reader on port 8100 (Ctrl+C stops it).
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Install Python 3.12+ first (https://www.python.org/downloads/)"; exit 1; }
[ -x .venv/bin/python ] || { echo "First run: preparing the Paper Reader..."; "$PY" -m venv .venv; }
. .venv/bin/activate
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if [ ! -f .env ]; then
  KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
  printf '# The Paper Reader settings, made on the first run. Add the key to Claude below.\nREADER_SECRET_KEY=%s\nREADER_ALLOWED_HOSTS=*\n# ANTHROPIC_API_KEY=sk-ant-...\n' "$KEY" > .env
  chmod 600 .env
fi
python manage.py migrate --verbosity 0
python manage.py collectstatic --noinput --verbosity 0
echo
echo "  The Paper Reader is running:  http://localhost:8100"
echo "  Press Ctrl+C to stop it."
echo
exec waitress-serve --listen=0.0.0.0:8100 --threads=8 site_config.wsgi:application
