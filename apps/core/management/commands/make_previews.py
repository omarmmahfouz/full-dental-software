import time

from django.core.management.base import BaseCommand

from apps.charting.models import ClinicalPhoto
from apps.core import previews
from apps.patients.models import PatientDocument


class Command(BaseCommand):
    help = ("Make the small copies (previews) of every clinical photo and scanned document that has none yet, "
            "so photo pages open quickly. Safe to re-run; run it once overnight after the update.")

    def handle(self, *args, **options):
        names = [ClinicalPhoto.objects.values_list("file", flat=True), PatientDocument.objects.values_list("file", flat=True)]
        made = checked = 0
        started = time.monotonic()
        for query in names:
            for name in query.iterator(chunk_size=2000):
                if not previews.can_preview(name):
                    continue
                checked += 1
                for size in previews.SIZES:
                    if previews.make_preview(name, size) is not None:
                        made += 1
                if checked % 500 == 0:
                    self.stdout.write(f"  {checked} pictures checked ({time.monotonic() - started:.0f} s)")
        self.stdout.write(self.style.SUCCESS(f"Pictures checked: {checked}. Their previews are ready ({made} small copies)."))
