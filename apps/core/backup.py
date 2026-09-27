"""Backups and exports: everything the system holds, in forms any other program can read.

There are two parts, because the photos grow to hundreds of gigabytes while the records stay small:

1. **The data**: one ZIP file of all the records (a few minutes, even with 10,000 patients).

       database.json      every record (Django format: put back with ``manage.py restore_backup``)
       database.sqlite3   the database file itself (trial / single-PC installations)
       excel/all-data.xlsx one sheet per table, readable column names and values
       csv/*.csv          the same tables as CSV (UTF-8), for any database or program
       README.txt         what is in the file and how to use it

   The newest ``BACKUP_KEEP`` are kept in ``BACKUP_DIR`` (data/backups by default).

2. **The photos and files** (ID scans, clinical photos, X-rays, stickers, invoices) are copied as they are to
   ``FILES_BACKUP_DIR`` (best on another disk): only the files that are new or changed since the last copy,
   and nothing is ever deleted there, so a photo deleted by mistake is still in the copy. The previews are
   not copied (the system makes them again).

``python manage.py backup`` does both; run it every night (Task Scheduler on Windows, the "nightly" service
with docker compose). Each run is written down (``BackupRun``): the owner's home page warns when a part failed
or has not run for more than a day and a half. ``--zip-files`` also puts the files in the ZIP (to move a
small system to a new PC in one file).
"""

import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

# Tables that Django rebuilds by itself, or that are only temporary.
SKIPPED = {"contenttypes.contenttype", "auth.permission", "sessions.session", "admin.logentry", "core.backuprun"}
SECRET_FIELDS = {"password"}  # kept in database.json (needed to log in again), never in Excel or CSV


def backup_dir():
    folder = Path(getattr(settings, "BACKUP_DIR", Path(settings.BASE_DIR) / "data" / "backups"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def data_models():
    """The tables to export, the system's own first (patients, schedule…), then the logins."""
    own = [m for m in apps.get_models() if m.__module__.startswith("apps.")]
    others = [m for m in apps.get_models() if not m.__module__.startswith("apps.")
              and m._meta.label_lower not in SKIPPED]
    return own + others


def _columns(model):
    columns = []
    for field in model._meta.get_fields():
        if field.auto_created and not field.concrete:
            continue  # reverse relations
        if field.name in SECRET_FIELDS:
            continue
        if field.many_to_many:
            columns.append((field, str(field.verbose_name), "m2m"))
        elif field.is_relation:
            columns.append((field, f"{field.verbose_name} (id)", "id"))
            columns.append((field, str(field.verbose_name), "label"))
        elif field.concrete:
            columns.append((field, str(field.verbose_name), "value"))
    return columns


class _Labels:
    """str() of related records, read once per table (readable Excel without thousands of queries)."""

    def __init__(self):
        self.cache = {}

    def get(self, model, pk):
        if pk is None:
            return ""
        labels = self.cache.get(model)
        if labels is None:
            # Every record of the table at once, with the records its name is made of (e.g. a visit's patient).
            labels = self.cache[model] = {obj.pk: str(obj) for obj in
                                          model._default_manager.select_related().iterator(chunk_size=2000)}
        return labels.get(pk, "")


def _cell(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
    if isinstance(value, (date, time, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "name") and isinstance(getattr(value, "name", None), str):  # files: path inside media/
        return value.name
    return str(value)


def table_rows(model, labels):
    """(headers, rows) of one table, with readable values (choice labels, names of related records).
    The rows are read a few thousand at a time, so a big table does not fill the memory."""
    columns = _columns(model)
    headers = [header for _field, header, _kind in columns]
    queryset = model._default_manager.all().order_by("pk")
    m2m = [field.name for field, _header, kind in columns if kind == "m2m"]
    if m2m:
        queryset = queryset.prefetch_related(*m2m)
    choices = {field.name: dict(field.flatchoices) for field, _header, kind in columns
               if kind == "value" and field.choices}

    def rows():
        for obj in queryset.iterator(chunk_size=2000):
            row = []
            for field, _header, kind in columns:
                if kind == "m2m":
                    row.append(", ".join(str(item) for item in getattr(obj, field.name).all()))
                elif kind == "id":
                    row.append(getattr(obj, field.attname))
                elif kind == "label":
                    row.append(labels.get(field.related_model, getattr(obj, field.attname)))
                elif field.name in choices:
                    value = getattr(obj, field.attname)
                    row.append(str(choices[field.name].get(value, value)))
                else:
                    row.append(_cell(getattr(obj, field.attname)))
            yield row
    return headers, rows()


def _sheet_name(model, used):
    name = "".join(c for c in str(model._meta.verbose_name_plural).capitalize() if c not in "[]:*?/\\")[:31]
    base, number = name, 2
    while name.lower() in used:
        suffix = f" {number}"
        name, number = base[:31 - len(suffix)] + suffix, number + 1
    used.add(name.lower())
    return name


def excel_workbook(output, labels=None, csv_bundle=None):
    """Write all tables to ``output`` (a path or file) as one Excel workbook: a sheet per table.
    Written row by row (write-only), so tens of thousands of visits need little memory. With ``csv_bundle``
    (a ZIP being written) each table also goes into it as csv/<table>.csv, in the same reading."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook(write_only=True)
    contents = workbook.create_sheet("Contents")
    contents.column_dimensions["A"].width = 34
    contents.column_dimensions["B"].width = 34

    def bold_row(sheet, values):
        cells = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            cell.font = Font(bold=True)
            cells.append(cell)
        sheet.append(cells)

    bold_row(contents, ["Table", "Sheet", "Records", "Exported"])
    labels, used = labels or _Labels(), {"contents"}
    with translation.override("en"):
        for model in data_models():
            headers, rows = table_rows(model, labels)
            sheet = workbook.create_sheet(_sheet_name(model, used))
            sheet.freeze_panes = "A2"
            for index, header in enumerate(headers, start=1):
                sheet.column_dimensions[get_column_letter(index)].width = min(max(len(header) + 2, 10), 40)
            bold_row(sheet, headers)
            count = 0
            with _csv_table(csv_bundle, model) as table:
                if table is not None:
                    table.writerow(headers)
                for row in rows:
                    sheet.append([_excel_safe(value) for value in row])
                    if table is not None:
                        table.writerow(["" if value is None else value for value in row])
                    count += 1
            contents.append([model._meta.label, sheet.title, count, timezone.localtime().strftime("%d/%m/%Y %H:%M")])
    workbook.save(output)


def _excel_safe(value):
    if isinstance(value, str):
        value = "".join(ch for ch in value if ch in "\t\n\r" or ord(ch) >= 32)  # Excel refuses control characters
        if value[:1] in ("=", "+", "-", "@") and len(value) > 1 and not value.lstrip("-+").replace(".", "").isdigit():
            return "'" + value  # never run as a formula
    return value


@contextmanager
def _csv_table(bundle, model):
    """A CSV writer for one table inside the ZIP ``bundle`` (None without a bundle)."""
    if bundle is None:
        yield None
        return
    name = f"csv/{model._meta.app_label}.{model._meta.model_name}.csv"
    with bundle.open(name, "w", force_zip64=True) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        yield csv.writer(text)


README = """CIA dental system — backup of all the data, made on {when}

database.json      Every record. To put it back into the system (same or newer version):
                     python manage.py restore_backup "{name}"
                   It is the standard Django fixture format: a developer can also load it with
                   "python manage.py loaddata database.json" or read it with any JSON tool.
database.sqlite3   The database file itself (only when the system uses SQLite, as in the trial).
excel/all-data.xlsx  One sheet per table with readable column names. "(id)" columns are the
                   numbers that link the tables (e.g. an appointment's patient (id) is the id
                   of a row in the Patients sheet).
csv/               The same tables as CSV files (UTF-8), to import into any database or program.
{files}
Keep a copy of this file outside the clinic PC (external disk or USB).
"""

FILES_IN_ZIP = """media/             All uploaded files: ID scans, clinical photos (media/Patient photos/…),
                   implant stickers, invoices, payment scans.
"""
FILES_ELSEWHERE = """The photos and uploaded files are NOT in this ZIP: they are copied every night, as they are, to
{folder}
To put them back on a new PC: python manage.py restore_files   (or copy that folder into data/media).
"""

# The backup warns on the owner's home page when a part has not run for longer than this.
BACKUP_OVERDUE = timedelta(hours=36)
SKIPPED_FOLDERS = {"previews"}  # made again by the system


def files_backup_dir():
    return Path(getattr(settings, "FILES_BACKUP_DIR", "") or backup_dir() / "files")


def _media_files(root):
    """Every uploaded file under ``root`` as (relative path, size, modified time), previews left out."""
    root = Path(root)
    for folder, subfolders, names in os.walk(root):
        relative_folder = Path(folder).relative_to(root)
        if relative_folder == Path("."):
            subfolders[:] = [name for name in subfolders if name not in SKIPPED_FOLDERS]
        for name in names:
            if name.endswith((".part", ".tmp")):
                continue
            path = Path(folder) / name
            try:
                info = path.stat()
            except OSError:
                continue
            yield (relative_folder / name).as_posix(), info.st_size, info.st_mtime


def copy_new_files(source, target, stdout=None):
    """Copy every file of ``source`` that ``target`` lacks, or has with another size or an older date.
    Nothing is deleted in ``target``. Returns (files checked, files copied, bytes copied)."""
    source, target = Path(source), Path(target)
    checked = copied = size = 0
    for relative, file_size, modified in _media_files(source):
        checked += 1
        destination = target / relative
        try:
            there = destination.stat()
            if there.st_size == file_size and there.st_mtime >= modified - 2:  # FAT/exFAT disks keep 2-second times
                continue
        except OSError:
            pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        shutil.copy2(source / relative, partial)  # keeps the file's date
        os.replace(partial, destination)
        copied += 1
        size += file_size
        if stdout is not None and copied % 1000 == 0:
            stdout.write(f"  {copied} files copied…")
    return checked, copied, size


def _run(kind, work):
    """Do one part of the backup and write down how it went. On an error the owner is told, and the error
    is raised again (so a scheduled task shows it failed)."""
    from .models import BackupRun, Notification
    from .notify import notify_roles
    from .roles import OWNER

    run = BackupRun.objects.create(kind=kind)
    try:
        details = work()
    except Exception as error:
        run.error = f"{type(error).__name__}: {error}"[:2000]
        run.finished_at = timezone.now()
        run.save()
        notify_roles((OWNER,), _("The backup failed: %(part)s"), _("%(error)s — see Settings → Backup."),
                     "/settings/backup/", Notification.Level.DANGER,
                     params={"part": run.get_kind_display(), "error": run.error[:200]})
        raise
    for key, value in details.items():
        setattr(run, key, value)
    run.ok, run.finished_at = True, timezone.now()
    run.save()
    return run


def create_backup(stdout=None, with_files=False):
    """Make the ZIP of all the data in the backup folder (with the uploaded files too when ``with_files``);
    returns its path. Old ZIPs beyond BACKUP_KEEP are removed."""
    from .models import BackupRun

    result = {}

    def work():
        result["path"] = path = _write_zip(with_files)
        return {"where": str(path), "size": path.stat().st_size}

    _run(BackupRun.Kind.DATABASE, work)
    if stdout is not None:
        stdout.write(f"Backup of the data saved: {result['path']}")
    return result["path"]


def backup_now(wait=20):
    """The "Make a backup now" button: make the data ZIP in its own thread and wait up to ``wait`` seconds,
    so the page never hangs for minutes with many patients. Returns the ZIP's path when it is ready,
    None while it is still being made (the Backup page shows it when it is done)."""
    if not getattr(settings, "BACKUP_IN_BACKGROUND", True):
        return create_backup()
    result = {}

    def work():
        try:
            result["path"] = create_backup()
        except Exception as error:  # written down in BackupRun and told to the owner by create_backup
            result["error"] = error
        finally:
            connection.close()  # this thread's own database connection

    thread = threading.Thread(target=work, name="backup-now")
    thread.start()
    thread.join(wait)
    if "error" in result:
        raise result["error"]
    return result.get("path")


def copy_files(stdout=None, target=None):
    """Copy the new and changed photos and files to the photo backup folder (FILES_BACKUP_DIR)."""
    from .models import BackupRun

    target = Path(target) if target else files_backup_dir()

    def work():
        media = Path(settings.MEDIA_ROOT).resolve()
        if target.resolve() == media or media in target.resolve().parents:
            raise ValueError(f"The photo backup folder ({target}) cannot be inside the photos folder ({media}).")
        target.mkdir(parents=True, exist_ok=True)
        checked, copied, size = copy_new_files(settings.MEDIA_ROOT, target, stdout)
        return {"where": str(target), "files_checked": checked, "files_copied": copied, "size": size}

    run = _run(BackupRun.Kind.FILES, work)
    if stdout is not None:
        stdout.write(f"Photos and files: {run.files_checked} checked, {run.files_copied} new or changed copied to {target}")
    return run


def restore_files(source=None, stdout=None):
    """Put the photos and files back from the photo backup folder (only those missing or older here)."""
    source = Path(source) if source else files_backup_dir()
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    checked, copied, _size = copy_new_files(source, settings.MEDIA_ROOT, stdout)
    if stdout is not None:
        stdout.write(f"Files put back from {source}: {copied} of {checked}.")
    return copied


def backup_status(now=None):
    """What the owner's home page shows: the last good run of each part, and whether something is wrong."""
    from .models import BackupRun

    now = now or timezone.now()
    parts = []
    for kind, label in BackupRun.Kind.choices:
        last = BackupRun.objects.filter(kind=kind).first()
        last_ok = last if last is not None and last.ok else BackupRun.objects.filter(kind=kind, ok=True).first()
        parts.append({
            "kind": kind, "label": label, "last": last, "last_ok": last_ok,
            "failed": last is not None and not last.ok and last.finished_at is not None,
            "overdue": last_ok is None or now - last_ok.started_at > BACKUP_OVERDUE,
        })
    return {"parts": parts, "problem": any(part["failed"] or part["overdue"] for part in parts)}


def _write_zip(with_files):
    folder = backup_dir()
    stamp = timezone.localtime().strftime("%Y-%m-%d_%H-%M-%S")
    path, number = folder / f"backup_{stamp}.zip", 1
    while path.exists():  # never overwrite a backup (e.g. the one being restored)
        number += 1
        path = folder / f"backup_{stamp}_{number}.zip"
    partial = path.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        dump = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        try:
            with dump:  # written to a file, not held in memory
                call_command("dumpdata", exclude=sorted(SKIPPED), natural_foreign=True, indent=1, stdout=dump)
            bundle.write(dump.name, "database.json")
        finally:
            os.unlink(dump.name)
        if connection.vendor == "sqlite":
            copy = _sqlite_copy()
            try:
                bundle.write(copy, "database.sqlite3")
            finally:
                os.unlink(copy)
        with tempfile.TemporaryFile() as workbook:
            excel_workbook(workbook, csv_bundle=bundle)  # the tables are read once, for Excel and CSV
            workbook.seek(0)
            with bundle.open("excel/all-data.xlsx", "w", force_zip64=True) as raw:
                shutil.copyfileobj(workbook, raw)
        if with_files:
            media_root = Path(settings.MEDIA_ROOT)
            for relative, _size, _modified in sorted(_media_files(media_root)):
                file = media_root / relative
                if folder not in file.parents:
                    bundle.write(file, f"media/{relative}", zipfile.ZIP_STORED)
        files_note = FILES_IN_ZIP if with_files else FILES_ELSEWHERE.format(folder=files_backup_dir())
        bundle.writestr("README.txt", README.format(when=timezone.localtime().strftime("%d/%m/%Y %H:%M"),
                                                    name=path.name, files=files_note))
    os.replace(partial, path)
    keep = getattr(settings, "BACKUP_KEEP", 10)
    for old in list_backups()[keep:]:
        old["path"].unlink(missing_ok=True)
    return path


def _sqlite_copy():
    """A consistent copy of the SQLite database, taken through the system's own connection
    (safe while the system is in use)."""
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    handle.close()
    connection.ensure_connection()
    target = sqlite3.connect(handle.name)
    try:
        if connection.in_atomic_block:  # inside a transaction SQLite's backup would wait for it to end
            target.executescript("\n".join(connection.connection.iterdump()))
        else:
            connection.connection.backup(target)
    finally:
        target.close()
    return handle.name


def list_backups():
    files = sorted(backup_dir().glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"path": p, "name": p.name, "size_mb": round(p.stat().st_size / 1024 / 1024, 1),
             "made_at": timezone.make_aware(datetime.fromtimestamp(p.stat().st_mtime))} for p in files]


def restore_backup(path, stdout=None):
    """Replace all data and uploaded files with those of a backup ZIP (a backup of the current
    state is made first). Used after moving to a new PC or after a big change went wrong."""
    safety = create_backup()
    with zipfile.ZipFile(path) as bundle:
        with tempfile.TemporaryDirectory() as work:
            fixture = Path(work) / "database.json"
            fixture.write_bytes(bundle.read("database.json"))
            call_command("flush", interactive=False, verbosity=0)
            call_command("loaddata", str(fixture), verbosity=0)
            media_root = Path(settings.MEDIA_ROOT)
            for member in bundle.namelist():
                if member.startswith("media/") and not member.endswith("/"):
                    target = (media_root / member[len("media/"):]).resolve()
                    if media_root.resolve() not in target.parents:
                        continue  # never write outside the media folder
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(member))
    if stdout is not None:
        stdout.write(f"Restored from {path}. The data before restoring was saved in {safety}.")
    return safety

