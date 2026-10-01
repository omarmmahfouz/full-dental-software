"""The owner's Security and health page (Settings → Security): a list of checks, each good or to fix, with what to
do; the space left on the disks; the slow pages and the page errors of the last day; the database's size. The same
checks are printed by ``python manage.py security_check``."""

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

DEV_KEY = "dev-only-insecure-key-change-me"
SLOW_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def disk_space(path):
    """(free GB, total GB, free %) of the disk holding ``path``, or None when it cannot be read."""
    try:
        target = Path(path)
        while not target.exists() and target.parent != target:
            target = target.parent
        usage = shutil.disk_usage(target)
    except OSError:
        return None
    return round(usage.free / 1024 ** 3, 1), round(usage.total / 1024 ** 3, 1), round(usage.free * 100 / usage.total)


def database_size():
    """The size of the data in MB (SQLite file, or PostgreSQL's database)."""
    try:
        if connection.vendor == "sqlite":
            return round(Path(settings.DATABASES["default"]["NAME"]).stat().st_size / 1024 ** 2, 1)
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database())")
                return round(cursor.fetchone()[0] / 1024 ** 2, 1)
    except Exception:  # noqa: BLE001 - only shown on the page
        return None
    return None


def slow_pages(hours=24, limit=200):
    """The slow pages written in slow-pages.log in the last ``hours``: [(time, line)], newest first."""
    if not settings.LOG_DIR:
        return []
    log = Path(settings.LOG_DIR) / "slow-pages.log"
    if not log.exists():
        return []
    since = timezone.localtime() - timedelta(hours=hours)
    rows = []
    try:
        with log.open(encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-2000:]
    except OSError:
        return []
    for line in lines:
        match = SLOW_LINE.match(line)
        if not match:
            continue
        try:
            when = timezone.make_aware(datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if when >= since:
            rows.append((when, line[len(match.group(1)):].strip()))
    return rows[::-1][:limit]


def security_checks():
    """[{"ok", "title", "detail"}]: what is right, and what to fix (with how)."""
    from django.contrib.auth import get_user_model

    from .backup import backup_status
    from .models import BackupRun, ClinicSettings

    checks = []

    def add(ok, title, good, fix):
        checks.append({"ok": bool(ok), "title": title, "detail": good if ok else fix})

    add(not settings.DEBUG, _("The system runs in normal mode (not the test mode)"),
        _("DJANGO_DEBUG is off: errors show a short page, not the program's details."),
        _("Set DJANGO_DEBUG=0 in the .env file of the server and restart it."))
    key = settings.SECRET_KEY or ""
    add(key != DEV_KEY and len(key) >= 40, _("The secret key is long and private"),
        _("It signs the logins: keep the .env file only on the server."),
        _("Write a long random DJANGO_SECRET_KEY in the .env file (the installer makes one) and restart."))
    networks = getattr(settings, "ALLOWED_NETWORKS", ["*"])
    add("*" not in networks, _("Only the clinic's network can open the system"),
        _("Devices outside the clinic's network are refused, even if the server is opened to the internet by "
          "mistake."),
        _("ALLOWED_NETWORKS is \"*\": every address may try. Use it only behind HTTPS and a VPN."))
    add("*" not in settings.ALLOWED_HOSTS, _("The server answers to its own names only"),
        _("ALLOWED_HOSTS lists the server's address and name."),
        _("ALLOWED_HOSTS is \"*\": write the server's address and name in DJANGO_ALLOWED_HOSTS."))
    https = getattr(settings, "SESSION_COOKIE_SECURE", False)
    add(https or "*" not in networks, _("The connection is protected"),
        _("HTTPS is on.") if https else _("On the clinic's own network. Turn HTTPS on (DJANGO_HTTPS=1) before the "
                                          "branches or the internet reach the server."),
        _("Turn HTTPS on (DJANGO_HTTPS=1) before opening the system outside the clinic."))
    options = ClinicSettings.get()
    add(options.idle_logout_minutes, _("A PC left open logs out by itself"),
        _("After %(n)s minutes without use.") % {"n": options.idle_logout_minutes},
        _("Set the minutes in Settings → Clinic options (e.g. 60)."))
    weak = list(get_user_model().objects.filter(is_active=True, profile__weak_password=True).values_list(
        "username", flat=True))
    add(not weak, _("Nobody logs in with an easy password"),
        _("The passwords seen at the logins are not short, common or like the username."),
        _("Easy passwords: %(names)s. Ask them to change it (user menu → Change password), or tick "
          "\"people with an easy password must change it\" in Clinic options.") % {"names": ", ".join(weak)})
    status = backup_status()
    data = next(part for part in status["parts"] if part["kind"] == BackupRun.Kind.DATABASE)
    files = next(part for part in status["parts"] if part["kind"] == BackupRun.Kind.FILES)
    last = data["last_ok"]
    add(last is not None and not data["overdue"], _("The data is backed up every night"),
        _("Last backup %(when)s.") % {"when": timezone.localtime(last.started_at).strftime("%d/%m/%Y %H:%M")}
        if last else "",
        _("No backup in the last day and a half: see Settings → Backup (the nightly task must run)."))
    add(last is not None and last.verified, _("The last backup was opened again and checked"),
        _("%(n)s records read back from it.") % {"n": last.records} if last else "",
        _("The last backup was not checked: make one now in Settings → Backup."))
    add(bool(getattr(settings, "BACKUP_COPY_DIR", "")) and last is not None and last.copy_where and not last.copy_error,
        _("A second copy of each backup is kept on another disk"),
        _("Copied to %(where)s.") % {"where": last.copy_where} if last else "",
        _("Set BACKUP_COPY_DIR to another disk or a network folder, and keep a second disk outside the clinic."))
    add(files["last_ok"] is not None and not files["overdue"], _("The photos are copied every night"),
        _("Only the new photos are copied, to %(where)s.") % {"where": files["last_ok"].where}
        if files["last_ok"] else "",
        _("The copy of the photos has not run in the last day and a half."))
    space = disk_space(settings.MEDIA_ROOT)
    add(space is None or (space[0] >= 5 and space[2] >= 10), _("There is room on the disk"),
        _("%(free)s GB free of %(total)s GB.") % {"free": space[0], "total": space[1]} if space else "",
        _("Only %(free)s GB free: move old backups or add a disk soon.") % {"free": space[0]} if space else "")
    return checks


def health():
    """The numbers of the Security and health page."""
    from .models import ProblemReport

    since = timezone.now() - timedelta(hours=24)
    return {
        "database_mb": database_size(),
        "data_disk": disk_space(settings.MEDIA_ROOT),
        "backup_disk": disk_space(settings.BACKUP_DIR),
        "slow": slow_pages(),
        "errors": ProblemReport.objects.filter(kind=ProblemReport.Kind.AUTOMATIC, last_seen_at__gte=since).count(),
        "database": connection.vendor,
    }


def short_device(agent):
    """ "Chrome on Windows", "Safari on iPad"... from the browser's own description."""
    agent = agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in agent), "")
    system = next((name for key, name in (("iPad", "iPad"), ("iPhone", "iPhone"), ("Android", "Android"),
                                          ("Windows", "Windows"), ("Mac OS", "Mac"), ("Linux", "Linux"))
                   if key in agent), "")
    if browser and system:
        return f"{browser} · {system}"
    return browser or system or agent[:40]
