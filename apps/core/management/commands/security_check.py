from django.core.management.base import BaseCommand
from django.utils import translation

from apps.core.health import security_checks


class Command(BaseCommand):
    help = ("The security and health checks of Settings → Security, printed: what is right and what to fix. "
            "Run it after installing or changing the server.")

    def handle(self, *args, **options):
        translation.activate("en")
        bad = 0
        for check in security_checks():
            mark = "OK  " if check["ok"] else "FIX "
            bad += not check["ok"]
            self.stdout.write(f"{mark} {check['title']}")
            if check["detail"]:
                self.stdout.write(f"     {check['detail']}")
        self.stdout.write(self.style.SUCCESS("All good.") if not bad else self.style.WARNING(f"{bad} to fix."))
