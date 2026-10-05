from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from apps.core import photo_folder


class Command(BaseCommand):
    help = ("Keep the photos, X-rays and scans in another folder (e.g. a bigger disk): copies every file there, checks "
            "each copy, then writes MEDIA_ROOT in .env. Restart the system afterwards. The old folder is kept.")

    def add_arguments(self, parser):
        parser.add_argument("folder", help='The new folder, e.g. "D:\\CIA photos"')
        parser.add_argument("--check", action="store_true", help="Only check the folder; copy nothing.")
        parser.add_argument("--no-env", action="store_true", help="Copy, but do not change .env (docker: change the "
                                                                   "MEDIA_HOST_DIR volume instead).")

    def handle(self, *args, folder, check=False, no_env=False, **options):
        translation.activate("en")
        findings = photo_folder.check(folder)
        for ok, text in findings:
            self.stdout.write(("  OK   " if ok else "  NO   ") + str(text))
        if not all(ok for ok, _text in findings):
            raise CommandError("The photos were not moved: correct the points marked NO and run it again.")
        if check:
            return
        self.stdout.write("Copying the photos (the system can stay open; run this again later to copy the new ones)…")
        copied, skipped, problems = photo_folder.copy_all(folder, say=self.stdout.write)
        self.stdout.write(f"{copied} files copied, {skipped} already there.")
        if problems:
            for problem in problems[:20]:
                self.stderr.write(f"  not copied: {problem}")
            raise CommandError(f"{len(problems)} files were not copied: the system keeps the old folder. "
                               "Correct the problem and run it again.")
        if no_env:
            self.stdout.write(self.style.SUCCESS("Copied. Now point MEDIA_HOST_DIR (docker-compose) to the new folder."))
            return
        path = photo_folder.write_env("MEDIA_ROOT", folder)
        self.stdout.write(self.style.SUCCESS(
            f"Done. {path} now says MEDIA_ROOT={folder}. Restart the system: new photos go to the new folder. "
            "The old folder was not deleted: delete it yourself after checking a few patients' photos."))
