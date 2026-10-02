"""Photos chosen in a form that came back with an error are kept on the server (round 13). A browser never fills a
file box again, so the ID photos were lost when the secretary corrected another box and saved a second time. The
photo is now kept for this person's session: the form shows it and saves it with the rest.

``keep(request, upload)`` → a token for a hidden box; ``kept(request, token)`` → its details for the page;
``take(request, token)`` → the file to save (and the kept copy is removed). Copies older than a day are removed by
``clean_old()`` (the nightly backup run)."""

import os
import time
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

SESSION_KEY = "kept_uploads"
FOLDER = "kept"
KEEP_AT_MOST = 10


def keep(request, upload):
    """Keep an uploaded file for this session; returns its token."""
    token = uuid.uuid4().hex
    extension = os.path.splitext(upload.name)[1].lower()[:6]
    upload.seek(0)
    path = default_storage.save(f"{FOLDER}/{token}{extension}", upload)
    upload.seek(0)
    files = dict(request.session.get(SESSION_KEY, {}))
    files[token] = {"path": path, "name": os.path.basename(upload.name)[:120], "at": int(time.time())}
    for old in sorted(files, key=lambda key: files[key]["at"])[:-KEEP_AT_MOST]:
        _remove(files.pop(old)["path"])
    request.session[SESSION_KEY] = files
    return token


def kept(request, token):
    """The kept file of this session for ``token`` ({"path", "name"}), or None."""
    info = request.session.get(SESSION_KEY, {}).get(token or "")
    if info and default_storage.exists(info["path"]):
        return info
    return None


def take(request, token):
    """The kept file as a new upload to save, or None. The kept copy is removed."""
    info = kept(request, token)
    if info is None:
        return None
    with default_storage.open(info["path"], "rb") as stored:
        content = ContentFile(stored.read(), name=info["name"])
    files = dict(request.session.get(SESSION_KEY, {}))
    files.pop(token, None)
    request.session[SESSION_KEY] = files
    _remove(info["path"])
    return content


def _remove(path):
    try:
        default_storage.delete(path)
    except OSError:
        pass


def clean_old(hours=24):
    """Remove the kept copies older than ``hours`` (forms never sent again)."""
    try:
        _, names = default_storage.listdir(FOLDER)
    except (FileNotFoundError, OSError):
        return 0
    limit, removed = time.time() - hours * 3600, 0
    for name in names:
        path = f"{FOLDER}/{name}"
        try:
            old = default_storage.get_modified_time(path).timestamp() < limit
        except (OSError, NotImplementedError):
            continue
        if old:
            _remove(path)
            removed += 1
    return removed


def carry(request, form, names):
    """After a save that came back with an error: keep the photos just chosen (when they have no error of their
    own) and the ones kept from an earlier try, so the page shows them and the next save takes them."""
    for name in names:
        if name not in form.fields:
            continue
        upload, token = form.files.get(name), form.data.get(f"{name}_kept", "")
        if upload and not form.errors.get(name):
            token = keep(request, upload)
        elif upload or kept(request, token) is None:
            token = ""
        form.fields[name].widget.kept_token = token


def chosen(request, form, name):
    """The photo to save for ``name``: the one chosen now, else the one kept from the last try (or None)."""
    return form.cleaned_data.get(name) or take(request, form.data.get(f"{name}_kept", ""))
