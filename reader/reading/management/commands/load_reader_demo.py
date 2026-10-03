"""Fill an empty Paper Reader with sample data (python manage.py load_reader_demo --password ...)."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from reading.demo import load_reader
from reading.models import PaperFile


class Command(BaseCommand):
    help = "Load the Paper Reader's sample data (an empty reader only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="The password of the sample logins.")

    def handle(self, *args, password, **options):
        if get_user_model().objects.exists() or PaperFile.objects.exists():
            raise CommandError("The reader is not empty: the sample data goes into an empty reader only.")
        if len(password) < 8:
            raise CommandError("Use a password of 8 characters or more.")
        load_reader(password)
        self.stdout.write(self.style.SUCCESS(
            "Sample data loaded. Logins: owner (the person in charge) and secretary, with the password given."))
