from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.backup import restore_backup


class Command(BaseCommand):
    help = ("Replace ALL data with that of a backup ZIP made by this system (and the uploaded files, when the ZIP "
            "has them). The current data is saved as a new backup first. Run 'migrate' before, on a new PC; "
            "then 'restore_files' to put the photos back from the photo backup folder.")

    def add_arguments(self, parser):
        parser.add_argument("backup", help="the backup_….zip file")
        parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    def handle(self, *args, backup, yes, **options):
        path = Path(backup)
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        if not yes and input(f"Replace all data with {path.name}? Type yes: ").strip().lower() != "yes":
            raise CommandError("Nothing changed.")
        restore_backup(path, stdout=self.stdout)
