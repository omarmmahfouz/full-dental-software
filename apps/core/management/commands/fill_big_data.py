import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.bigdata import fill


class Command(BaseCommand):
    help = ("TEST COPY ONLY: add thousands of made-up patients with two years of visits, bills, payments and photo "
            "records, to see how the system works with clinic-sized data (e.g. after load_demo_data). "
            "Never on the clinic's real database.")

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=10_000)
        parser.add_argument("--test-copy", action="store_true",
                            help="confirm this is a test copy (needed when DJANGO_DEBUG is off)")

    def handle(self, *args, patients, test_copy, **options):
        if not settings.DEBUG and not test_copy:
            raise CommandError("This adds made-up patients. Run it on a test copy only, with DJANGO_DEBUG=1 "
                               "or --test-copy.")
        started = time.monotonic()
        try:
            added = fill(patients=patients)
        except ValueError as error:
            raise CommandError(str(error))
        summary = ", ".join(f"{count} {name}" for name, count in added.items())
        self.stdout.write(self.style.SUCCESS(f"Added {summary} in {time.monotonic() - started:.0f} s."))
