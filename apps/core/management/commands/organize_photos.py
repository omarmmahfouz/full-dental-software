from django.core.management.base import BaseCommand

from apps.charting.models import ClinicalPhoto
from apps.charting.photo_files import organize


class Command(BaseCommand):
    help = "Move clinical photos into readable folders (Patient photos / patient / stage / shot). Safe to re-run."

    def handle(self, *args, **options):
        moved = sum(organize(photo) for photo in ClinicalPhoto.objects.select_related("patient", "photo_type"))
        self.stdout.write(self.style.SUCCESS(f"Photos moved into readable folders: {moved}"))
