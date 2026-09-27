import os
import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.backup import create_backup


def test_copy_env(folder):
    """The settings of the test copy: its own small database file and folders, and the banner on every page."""
    return {
        **os.environ,
        "DB_ENGINE": "sqlite", "SQLITE_PATH": str(folder / "db.sqlite3"), "MEDIA_ROOT": str(folder / "media"),
        "BACKUP_DIR": str(folder / "backups"), "FILES_BACKUP_DIR": str(folder / "files-backup"),
        "LOG_DIR": str(folder / "logs"), "MEDIA_SENDFILE": "", "TEST_COPY": "1",
    }


class Command(BaseCommand):
    help = ("Make a TEST COPY of the system with today's data (in the folder test-copy), to try a new version or a "
            "big change without touching the real data. Every page of the copy shows a yellow TEST COPY banner. "
            "The photos are not copied (they stay in the real system only). With --serve PORT the copy is then "
            "started on that port, e.g. http://<server-ip>:8001/.")

    def add_arguments(self, parser):
        parser.add_argument("--folder", default=str(Path(settings.BASE_DIR) / "test-copy"))
        parser.add_argument("--serve", type=int, metavar="PORT", help="then start the test copy on this port")
        parser.add_argument("--keep", action="store_true", help="start the copy made before, without new data")

    def handle(self, *args, folder, serve=None, keep=False, **options):
        if settings.TEST_COPY:
            raise CommandError("This is already a test copy.")
        folder = Path(folder).resolve()
        env = test_copy_env(folder)
        run = [sys.executable, str(Path(settings.BASE_DIR) / "manage.py")]
        if not (keep and (folder / "db.sqlite3").exists()):
            self.stdout.write("1/3 A backup of today's data…")
            backup = create_backup()
            if folder.exists():
                shutil.rmtree(folder)  # the copy is always made new: nothing done in the old one is kept
            (folder / "media").mkdir(parents=True)
            self.stdout.write("2/3 The test copy's database…")
            subprocess.run(run + ["migrate", "--verbosity", "0"], env=env, check=True, cwd=settings.BASE_DIR)
            self.stdout.write("3/3 Putting today's data in it (a few minutes with many patients)…")
            subprocess.run(run + ["restore_backup", str(backup), "--yes"], env=env, check=True, cwd=settings.BASE_DIR,
                           stdout=subprocess.DEVNULL)
            self.stdout.write(self.style.SUCCESS(f"Test copy ready in {folder}."))
        if serve:
            self.stdout.write(f"Starting the test copy: http://<this server's IP>:{serve}/  (Ctrl+C to stop)")
            waitress = shutil.which("waitress-serve")
            command = ([waitress, f"--listen=*:{serve}", "config.wsgi:application"] if waitress
                       else run + ["runserver", f"0.0.0.0:{serve}", "--noreload"])
            try:
                subprocess.run(command, env=env, cwd=settings.BASE_DIR)
            except KeyboardInterrupt:
                pass
