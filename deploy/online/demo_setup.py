"""Helpers for the online demo's start (deploy/online/start.sh).

    python deploy/online/demo_setup.py wait-page  answers every page with "The system is starting" on $PORT
    python deploy/online/demo_setup.py prepare    picks the database address, migrates, fills the sample data on an
                                                  empty database (or adds a newer version's lists after an update)
                                                  and writes the address to DB_HOST_FILE: one start of Django only,
                                                  which counts on a small server
    python deploy/online/demo_setup.py host       prints the first database address of DB_HOSTS that answers
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

STARTING_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="10">
<title>Starting</title><style>
body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#f4f6f8;color:#1d2a36}
main{text-align:center;padding:24px;max-width:440px}.dot{width:42px;height:42px;border-radius:50%;margin:0 auto 18px;
border:4px solid #cfd8e0;border-top-color:#1f6f8b;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(1turn)}}
@media (prefers-reduced-motion:reduce){.dot{animation:none}}p{line-height:1.6}</style></head>
<body><main><div class="dot"></div><h1>The system is starting</h1>
<p>This page opens it by itself as soon as it is ready: usually under a minute
(the very first time, or after an update, it can take several minutes).</p>
<p dir="rtl" lang="ar">النظام يبدأ الآن. ستفتح الصفحة وحدها عندما يكون جاهزًا، غالبًا خلال دقيقة
(أول مرة أو بعد تحديث قد تأخذ عدة دقائق).</p></main></body></html>""".encode()


def wait_page():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Starting(BaseHTTPRequestHandler):
        def _answer(self, body=True):
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Retry-After", "10")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(STARTING_PAGE)))
            self.end_headers()
            if body:
                self.wfile.write(STARTING_PAGE)

        def do_GET(self):
            self._answer()

        def do_HEAD(self):
            self._answer(body=False)

        do_POST = do_GET

        def log_message(self, *args):
            pass

    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Starting).serve_forever()


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


def prepare():
    host = pick_host()
    os.environ["DB_HOST"] = host
    print(f"Database: {host}", flush=True)

    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    updated = bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    call_command("migrate", "--noinput", verbosity=1 if updated else 0)

    if not get_user_model().objects.exists():
        password = os.environ.get("DEMO_PASSWORD") or sys.exit("DEMO_PASSWORD is not set.")
        print("An empty database: the lists and the sample data are filled (several minutes, once).", flush=True)
        with transaction.atomic():  # all or nothing: a server stopped half way leaves an empty database
            call_command("setup_clinic")
            call_command("load_demo_data", "--password", password)
        print("Sample data loaded.", flush=True)
    elif updated:
        # A newer version: its lists, rooms and places are added (setup_clinic can run many times).
        call_command("setup_clinic")
    Path(os.environ.get("DB_HOST_FILE", "/tmp/db_host")).write_text(host)


def main(action):
    if action == "wait-page":
        wait_page()
        return 0
    if action == "host":
        print(pick_host())
        return 0
    if action == "prepare":
        prepare()
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
