from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.backup import files_backup_dir, restore_files


class Command(BaseCommand):
    help = ("Put the photos and uploaded files back from the photo backup folder (e.g. on a new PC, after "
            "restore_backup). Only files missing here, or older here, are copied; nothing is deleted.")

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", help="the photo backup folder (default: FILES_BACKUP_DIR)")

    def handle(self, *args, source=None, **options):
        folder = Path(source) if source else files_backup_dir()
        if not folder.is_dir():
            raise CommandError(f"No such folder: {folder}")
        restore_files(folder, stdout=self.stdout)
