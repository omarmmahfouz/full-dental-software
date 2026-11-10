"""Open every page each login can reach by its links, and say what is wrong: a link that answers "not allowed",
a page that stops with an error, a page that reads the database too many times or takes long.

    DJANGO_DEBUG=1 python manage.py check_pages                 # every active login, on the sample data
    DJANGO_DEBUG=1 python manage.py check_pages --users owner,secretary --max-queries 80

Only pages are opened (GET), nothing is sent. Run it on the sample data or a test copy before pushing: it is what
found the links of the "Up" button that led to closed pages. With thousands of patients (``fill_big_data``) the slow
pages show."""

import re
import time
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

SKIP = re.compile(r"^/(logout|static|media|admin|jsi18n)|/(delete|remove)/|backup/(download|excel)|export|\.xlsx|/download")
HREF = re.compile(r'href="(/[^"#]*)')


def pattern(url):
    """/patients/12/?q=x and /patients/7/?q=y are the same kind of page."""
    path, _mark, query = url.partition("?")
    keys = sorted(part.split("=")[0] for part in query.split("&") if part)
    return re.sub(r"\d+", "N", path) + ("?" + "&".join(keys) if keys else "")


def crawl(user, per_pattern=2, max_pages=700):
    """[{url, status, queries, ms, from}] of the pages ``user`` reaches from the home page."""
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)
    seen, counts, queue, source, rows = set(), defaultdict(int), ["/"], {}, []
    while queue and len(rows) < max_pages:
        url = queue.pop(0).replace("&amp;", "&")
        if url in seen or SKIP.search(url):
            continue
        seen.add(url)
        if counts[pattern(url)] >= per_pattern:
            continue
        counts[pattern(url)] += 1
        connection.queries_log.clear()
        started = time.perf_counter()
        error = ""
        try:
            with CaptureQueriesContext(connection) as queries:
                response = client.get(url)
            status, read = response.status_code, len(queries)
        except Exception as problem:  # a page that stops with an error
            response, status, read, error = None, 500, 0, repr(problem)[:200]
        rows.append({"url": url, "status": status, "queries": read, "from": source.get(url, ""), "error": error,
                     "ms": int((time.perf_counter() - started) * 1000)})
        if response is None:
            continue
        if status == 200 and "text/html" in response.get("Content-Type", ""):
            for link in HREF.findall(response.content.decode("utf-8", "replace")):
                link = link.replace("&amp;", "&")
                if link not in seen:
                    queue.append(link)
                    source.setdefault(link, url)
        elif status in (301, 302) and response["Location"].startswith("/"):
            queue.append(response["Location"])
            source.setdefault(response["Location"], url)
    return rows


class Command(BaseCommand):
    help = ("TEST COPY ONLY: open every page each login reaches by its links and report the links that answer "
            "'not allowed', the pages with an error and the heavy pages.")

    def add_arguments(self, parser):
        parser.add_argument("--users", default="", help="usernames, comma separated (default: every active login)")
        parser.add_argument("--max-queries", type=int, default=150, help="report a page that reads more than this")
        parser.add_argument("--max-ms", type=int, default=2000, help="report a page that takes longer than this")
        parser.add_argument("--max-pages", type=int, default=700, help="pages opened for each login at most")
        parser.add_argument("--test-copy", action="store_true",
                            help="confirm this is a test copy (needed when DJANGO_DEBUG is off)")

    def handle(self, *args, users, max_queries, max_ms, max_pages, test_copy, **options):
        if not settings.DEBUG and not test_copy:
            raise CommandError("This opens every page as every login. Run it on the sample data or a test copy, "
                               "with DJANGO_DEBUG=1 or --test-copy.")
        people = get_user_model().objects.filter(is_active=True).order_by("pk")
        if users:
            people = people.filter(username__in=[name.strip() for name in users.split(",")])
        opened = problems = 0
        for user in people:
            rows = crawl(user, max_pages=max_pages)
            opened += len(rows)
            for row in rows:
                trouble = []
                if row["status"] not in (200, 301, 302):
                    trouble.append(f"answers {row['status']}" + (f", linked from {row['from']}" if row["from"] else "")
                                   + (f" ({row['error']})" if row["error"] else ""))
                if row["queries"] > max_queries:
                    trouble.append(f"reads the database {row['queries']} times")
                if row["ms"] > max_ms:
                    trouble.append(f"takes {row['ms']} ms")
                if trouble:
                    problems += 1
                    self.stdout.write(f"{user.username}: {row['url']} " + "; ".join(trouble))
        summary = f"{opened} pages opened for {people.count()} login(s): {problems} with a problem."
        self.stdout.write(self.style.SUCCESS(summary) if not problems else self.style.WARNING(summary))
        return None
