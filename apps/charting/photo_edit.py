"""Photos edited before they go in the log book (cropped, turned, mirrored, lighter...): the edited photo takes the
photo's place and name in its folder, and the photo as it was taken is kept next to it, "(original)", so it can
always be put back."""

import io
import os

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.translation import gettext as _
from PIL import Image

from apps.core import previews

from .photo_files import readable_path

MAX_EDITED_MB = 25


def _original_name(photo):
    base, ext = os.path.splitext(readable_path(photo, photo.file.name))
    return default_storage.generate_filename(f"{base} (original){ext}")


def _move(old, new):
    with default_storage.open(old, "rb") as source:
        saved = default_storage.save(new, source)
    default_storage.delete(old)
    previews.delete_previews(old)
    return saved


def check_picture(data):
    if len(data) > MAX_EDITED_MB * 1024 * 1024:
        raise ValidationError(_("The picture is too large."))
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as error:  # noqa: BLE001 - anything Pillow cannot read is refused
        raise ValidationError(_("This is not a picture.")) from error


@transaction.atomic
def save_edited(photo, data):
    """Put the edited picture (JPEG bytes from the page) in the photo's place; keep the first original."""
    check_picture(data)
    old = photo.file.name
    if not photo.original:
        photo.original.name = _move(old, _original_name(photo))
    else:
        default_storage.delete(old)
        previews.delete_previews(old)
    name = os.path.splitext(os.path.basename(readable_path(photo, old)))[0] + ".jpg"
    photo.file.save(name, ContentFile(data), save=False)
    photo.save(update_fields=["file", "original", "updated_at"])
    previews.make_previews(photo.file.name, sizes=("small", "medium"))
    return photo


@transaction.atomic
def restore_original(photo):
    """Undo the editing: the photo as it was taken goes back in its place."""
    if not photo.original:
        return photo
    default_storage.delete(photo.file.name)
    previews.delete_previews(photo.file.name)
    photo.file.name = _move(photo.original.name,
                            default_storage.generate_filename(readable_path(photo, photo.original.name)))
    photo.original.name = ""
    photo.save(update_fields=["file", "original", "updated_at"])
    previews.make_previews(photo.file.name, sizes=("small", "medium"))
    return photo
