"""Read the paper files waiting (python manage.py read_paper_files). The program does it by itself in the
background while it is open; this command is for a PC where the program is restarted often, or for a scheduled
task: it cuts the new files into pages, sends them, and waits for the batches (asking every minute) until all are
read."""

from django.core.management.base import BaseCommand

from reading.worker import run_once, run_until_done


class Command(BaseCommand):
    help = "Read the paper files waiting (send the pages to Claude, collect and check the answers)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One round only: do not wait for the batches.")

    def handle(self, *args, once=False, **options):
        if once:
            self.stdout.write(f"Paper files: {run_once()}")
        else:
            run_until_done()
            self.stdout.write("Paper files: all read.")
