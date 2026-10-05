"""Where the photos, X-rays and scans are kept (round 15): the folder in use, a check of another folder before the
photos move there, and the move itself (``manage.py move_photos``, ``move_photos.bat``).

The folder is MEDIA_ROOT (the .env file, or the docker-compose volume MEDIA_HOST_DIR). Moving copies every file,
checks each copy by its size, then writes the new folder in .env: the system uses it from its next start. The old
folder is never deleted: the owner removes it after looking at the photos in the new place."""

import os
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.utils.translation import gettext as _

CACHE_KEY = "photo-folder-size"


def folder_size(root, limit=500_000):
    """(number of files, bytes) under a folder; counted again at most every 10 minutes (thousands of photos)."""
    root = Path(root)
    cached = cache.get(CACHE_KEY)
    if cached and cached[0] == str(root):
        return cached[1], cached[2]
    count = size = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                size += os.path.getsize(os.path.join(folder, name))
            except OSError:
                continue
            count += 1
            if count >= limit:
                break
    cache.set(CACHE_KEY, (str(root), count, size), 600)
    return count, size


def disk_space(path):
    """(free, total) bytes of the disk holding ``path`` (or of the nearest folder above it that exists)."""
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None, None
    return usage.free, usage.total


def current():
    root = Path(settings.MEDIA_ROOT).resolve()
    count, size = folder_size(root) if root.exists() else (0, 0)
    free, total = disk_space(root)
    return {"path": str(root), "exists": root.exists(), "files": count, "size": size, "free": free, "total": total,
            "in_docker": Path("/.dockerenv").exists()}


def check(new_path):
    """What stands in the way of keeping the photos in ``new_path``: a list of (ok, text), the problems first."""
    findings = []
    text = (new_path or "").strip().strip('"')
    if not text:
        return [(False, _("Write the folder, e.g. D:\\CIA photos."))]
    new = Path(text).expanduser()
    if not new.is_absolute():
        return [(False, _("Write the whole folder, starting with the disk (D:\\…) or / on Linux."))]
    old = Path(settings.MEDIA_ROOT).resolve()
    new = new.resolve()
    if new == old:
        return [(False, _("This is the folder the photos are in now."))]
    if old in new.parents or new in old.parents:
        findings.append((False, _("The new folder cannot be inside the old one, or the old one inside it.")))
    backups = [Path(p).resolve() for p in (settings.BACKUP_DIR, settings.FILES_BACKUP_DIR, settings.BACKUP_COPY_DIR) if p]
    if any(new == b or b in new.parents for b in backups):
        findings.append((False, _("This is a backup folder: keep the photos and their backup apart.")))
    try:
        new.mkdir(parents=True, exist_ok=True)
        probe = new / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        findings.append((True, _("The folder can be written to.")))
    except OSError as error:
        findings.append((False, _("The system cannot write there: %(error)s") % {"error": error}))
        return findings
    _count, needed = folder_size(old) if old.exists() else (0, 0)
    free, _total = disk_space(new)
    if free is not None and free < needed * 1.2 + 1024 ** 3:
        findings.append((False, _("Not enough free space there: %(free)s free, the photos need %(need)s and room to "
                                  "grow.") % {"free": human(free), "need": human(needed)}))
    elif free is not None:
        findings.append((True, _("Free space: %(free)s (the photos take %(need)s).")
                         % {"free": human(free), "need": human(needed)}))
    findings.sort(key=lambda finding: finding[0])
    return findings


def human(size):
    from django.template.defaultfilters import filesizeformat

    return filesizeformat(size or 0)


def copy_all(new_path, say=print):
    """Copy every file to ``new_path`` (the same sub-folders); a file already there with the same size is skipped.
    Returns (copied, skipped, problems)."""
    old, new = Path(settings.MEDIA_ROOT).resolve(), Path(new_path).resolve()
    copied = skipped = 0
    problems = []
    for folder, _dirs, files in os.walk(old):
        target_folder = new / Path(folder).relative_to(old)
        target_folder.mkdir(parents=True, exist_ok=True)
        for name in files:
            source, target = Path(folder) / name, target_folder / name
            try:
                if target.exists() and target.stat().st_size == source.stat().st_size:
                    skipped += 1
                    continue
                shutil.copy2(source, target)
                if target.stat().st_size != source.stat().st_size:
                    problems.append(str(source))
                    continue
                copied += 1
                if copied % 1000 == 0:
                    say(f"{copied} files copied…")
            except OSError as error:
                problems.append(f"{source}: {error}")
    return copied, skipped, problems


def write_env(key, value):
    """Set ``key=value`` in the .env file the system reads at its start (the line is replaced or added)."""
    path = Path(settings.BASE_DIR) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    line = f"{key}={value}"
    for index, old in enumerate(lines):
        if old.strip().startswith(f"{key}=") or old.strip().startswith(f"# {key}="):
            lines[index] = line
            break
    else:
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
