#!/bin/sh
# TRIAL on a Mac or Linux PC:  sh trial-mac-linux.sh
# Creates a practice database with sample data and starts the system on port 8000.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Install Python 3.12+ first (https://www.python.org/downloads/)"; exit 1; }
[ -x .venv/bin/python ] || { echo "First run: preparing the system..."; "$PY" -m venv .venv; }
. .venv/bin/activate
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if [ ! -f .env ]; then
  printf '# Trial settings created by trial-mac-linux.sh - NOT for the real clinic server\nDJANGO_DEBUG=1\nDB_ENGINE=sqlite\nDJANGO_ALLOWED_HOSTS=*\n' > .env
fi
python manage.py migrate --verbosity 0
python manage.py setup_clinic >/dev/null
python manage.py load_demo_data --password demo12345 --if-empty
echo
echo "  The system is running:  http://localhost:8000"
echo "  Users (password demo12345): owner  headcia  teamhead  dentist1  dentist2  secretary  secretary2  stock"
echo "  Press Ctrl+C to stop."
echo
python manage.py runserver 0.0.0.0:8000
