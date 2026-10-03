#!/bin/sh
# A PRACTICE Paper Reader with sample files:  sh trial-mac-linux.sh
# Nothing is sent to Claude (no key needed). Its data is in "data-trial", apart from the real reader.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Install Python 3.12+ first (https://www.python.org/downloads/)"; exit 1; }
[ -x .venv/bin/python ] || { echo "First run: preparing the Paper Reader..."; "$PY" -m venv .venv; }
. .venv/bin/activate
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
export READER_DEBUG=1 READER_DATA_DIR="$(pwd)/data-trial" READER_ALLOWED_HOSTS='*' ANTHROPIC_API_KEY=
FRESH=
[ -f "$READER_DATA_DIR/reader.sqlite3" ] || FRESH=1
python manage.py migrate --verbosity 0
[ -z "$FRESH" ] || python manage.py load_reader_demo --password demo12345
echo
echo "  The PRACTICE Paper Reader is running:  http://localhost:8100"
echo "  Logins (password demo12345): owner (the person in charge)  secretary"
echo "  Press Ctrl+C to stop it."
echo
exec python manage.py runserver 0.0.0.0:8100 --noreload
