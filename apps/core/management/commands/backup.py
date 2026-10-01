from django.core.management.base import BaseCommand

from apps.core.backup import copy_files, create_backup, maintain_database


class Command(BaseCommand):
    help = ("The nightly backup: a ZIP of all the data (JSON, Excel, CSV and the database file) in the backup folder, "
            "checked and copied to BACKUP_COPY_DIR, then a copy of the new and changed photos and files to the photo "
            "backup folder (FILES_BACKUP_DIR), then the database is tidied. "
            "Run it every night from the Windows Task Scheduler (deploy/windows/backup.bat) or cron.")

    def add_arguments(self, parser):
        parser.add_argument("--no-files", action="store_true", help="only the data, not the photo copy")
        parser.add_argument("--zip-files", action="store_true",
                            help="also put every uploaded file in the ZIP (to move a small system in one file)")
        parser.add_argument("--files-to", help="copy the photos to this folder instead of FILES_BACKUP_DIR")

    def handle(self, *args, no_files=False, zip_files=False, files_to=None, **options):
        create_backup(stdout=self.stdout, with_files=zip_files)
        if not no_files:
            copy_files(stdout=self.stdout, target=files_to)
        removed = maintain_database()
        self.stdout.write(f"Database tidied ({removed} old log lines removed).")
