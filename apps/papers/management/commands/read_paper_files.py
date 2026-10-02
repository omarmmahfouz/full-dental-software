"""Read the old paper files waiting (python manage.py read_paper_files). The server does it by itself in the
background; this command is for a server that is restarted often, or to run from the nightly task: it cuts the new
files into pages, sends them, and waits for the batches (asking every minute) until all are read."""

from django.core.management.base import BaseCommand

from apps.papers.worker import run_once, run_until_done


class Command(BaseCommand):
    help = "Read the old paper files waiting (send the pages to Claude, collect and check the answers)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One round only: do not wait for the batches.")

    def handle(self, *args, once=False, **options):
        if once:
            self.stdout.write(f"Paper files: {run_once()}")
        else:
            run_until_done()
            self.stdout.write("Paper files: all read.")
