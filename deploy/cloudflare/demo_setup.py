"""Helpers for the online demo's start (deploy/cloudflare/start.sh).

    python deploy/cloudflare/demo_setup.py host       prints the first database address of DB_HOSTS that answers
    python deploy/cloudflare/demo_setup.py is-empty   exit code 0 when the database has no logins yet
    python deploy/cloudflare/demo_setup.py fill       the lists and the sample data (password DEMO_PASSWORD), at once
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def pick_host():
    import psycopg

    hosts = [h.strip() for h in os.environ.get("DB_HOSTS", os.environ.get("DB_HOST", "")).split(",") if h.strip()]
    errors = []
    for host in hosts:
        try:
            psycopg.connect(host=host, port=os.environ.get("DB_PORT", "5432"), dbname=os.environ.get("DB_NAME"),
                            user=os.environ.get("DB_USER"), password=os.environ.get("DB_PASSWORD"),
                            connect_timeout=10).close()
            return host
        except Exception as error:  # the wrong pooler says "Tenant or user not found"
            errors.append(f"{host}: {str(error).strip()[:200]}")
    sys.exit("No database address answered:\n" + "\n".join(errors))


def main(action):
    if action == "host":
        print(pick_host())
        return 0

    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import transaction

    empty = not get_user_model().objects.exists()
    if action == "is-empty":
        return 0 if empty else 1
    if action == "fill":
        if not empty:
            print("The sample data is already there.")
            return 0
        password = os.environ.get("DEMO_PASSWORD") or sys.exit("DEMO_PASSWORD is not set.")
        with transaction.atomic():  # all or nothing: a container stopped half way leaves an empty database
            call_command("setup_clinic")
            call_command("load_demo_data", "--password", password)
        print("Sample data loaded.")
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
