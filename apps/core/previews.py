"""Small copies of uploaded pictures, so pages with many photos open quickly, even on a tablet.

The original stays as it was, in its readable folder. Its previews are kept apart:

    media/previews/small/Patient photos/CIA-00020 حسن محمود/1 Preoperative photos (1st visit)/Bite_25-09-2026.jpg.jpg
    media/previews/medium/…

- "small" (480 px) is for the photo grids and the document cards (about 40 KB instead of several MB).
- "medium" (1600 px) is for the pages that show photos large: the log book and the case report.

A preview is made when the picture is uploaded, else the first time a page asks for it, or for every
picture at once with ``python manage.py make_previews``. It is made again when the original changes.
Opening a photo itself still gives the original, at full quality."""

import os
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

ROOT = "previews"
SIZES = {"small": 480, "medium": 1600}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
QUALITY = 82


def can_preview(name):
    return bool(name) and os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS


def preview_name(name, size="small"):
    return f"{ROOT}/{size}/{name}.jpg"


def split(path):
    """(size, original name) for a preview's path, else None."""
    parts = path.split("/", 2)
    if len(parts) == 3 and parts[0] == ROOT and parts[1] in SIZES and parts[2].endswith(".jpg"):
        original = parts[2][:-4]
        if can_preview(original):
            return parts[1], original
    return None


def _path(name):
    return default_storage.path(name)


def make_preview(name, size="small"):
    """Make (or bring up to date) one preview; returns its name, or None when the picture cannot be read."""
    source, target = _path(name), _path(preview_name(name, size))
    try:
        source_time = os.stat(source).st_mtime
    except OSError:
        return None
    try:
        if os.stat(target).st_mtime >= source_time:
            return preview_name(name, size)
    except OSError:
        pass
    edge = SIZES[size]
    try:
        with Image.open(source) as image:
            image.draft("RGB", (edge, edge))  # JPEG: read at a smaller scale, much faster for big photos
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS, reducing_gap=3.0)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".part")
            try:
                with os.fdopen(handle, "wb") as out:
                    image.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
                os.chmod(temporary, settings.FILE_UPLOAD_PERMISSIONS or 0o644)  # like the uploaded files
                os.replace(temporary, target)  # never a half-written preview, even with two requests at once
            except BaseException:
                if os.path.exists(temporary):
                    os.remove(temporary)
                raise
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return preview_name(name, size)


def make_previews(name, sizes=("small",)):
    """Make the previews of one uploaded picture (nothing for PDFs and videos). On upload only the small one
    is made (a tenth of a second); the large one is made the first time a page shows it."""
    if can_preview(name):
        for size in sizes:
            make_preview(name, size)


def delete_previews(name):
    """Remove the previews of a picture that was deleted, moved or changed."""
    if not can_preview(name):
        return
    for size in SIZES:
        try:
            os.remove(_path(preview_name(name, size)))
        except OSError:
            pass
