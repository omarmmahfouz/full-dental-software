from django.core.management.base import BaseCommand

from apps.core.backup import create_backup


class Command(BaseCommand):
    help = ("Make a full backup ZIP (all data as JSON, Excel and CSV, the database file and all uploaded files) "
            "in the backup folder. Run it every night from the Windows Task Scheduler or cron.")

    def handle(self, *args, **options):
        create_backup(stdout=self.stdout)
