"""Clinical photos are kept in folders anyone can open without the software:

    data/media/Patient photos/CIA-00020 حسن محمود/1 Preoperative photos (1st visit)/Bite_right_side_25-09-2026.jpg

one folder per patient, one per stage, each file named by its shot (the procedure step), the
teeth and the date. The same layout is used for the ZIP download of a patient's photos."""

import os
import re
import tempfile
import zipfile

from django.core.files.storage import default_storage

ROOT = "Patient photos"

# Numbered so they sort in the order of the case. Not translated: folder names stay the same.
STAGE_FOLDERS = {
    "diagnostic": "1 Preoperative photos (1st visit)",
    "surgery": "2 Surgery photos",
    "sinus_gbr": "3 Sinus lift and GBR photos",
    "follow_up": "4 Follow-up photos",
    "soft_tissue": "5 Soft tissue surgery photos",
    "second_stage": "6 Second stage photos",
    "impression": "7 Impression photos",
    "delivery": "8 Try-in and delivery photos",
}

_NOT_ALLOWED = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')  # not allowed in Windows file names


def clean(text, limit=80):
    return _NOT_ALLOWED.sub(" ", str(text or "")).strip(" .")[:limit].strip(" .") or "-"


def patient_folder(patient):
    return clean(f"{patient.file_number} {patient.full_name}", 100)


def stage_folder(stage):
    return STAGE_FOLDERS.get(stage, clean(stage))


def file_title(photo):
    """The shot (procedure step), the teeth and the date, e.g. "Implant placed with cover screw 36 25-09-2026"."""
    shot = photo.photo_type.name_en if photo.photo_type_id else (photo.notes or "Other photo")
    teeth = (photo.teeth or "").replace(", ", "-")
    taken = photo.taken_on.strftime("%d-%m-%Y") if photo.taken_on else ""
    return clean(" ".join(part for part in (shot, teeth, taken) if part), 120)


def readable_path(photo, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"{ROOT}/{patient_folder(photo.patient)}/{stage_folder(photo.stage)}/{file_title(photo)}{ext}"


def is_organized(photo):
    return photo.file.name.startswith(f"{ROOT}/{patient_folder(photo.patient)}/{stage_folder(photo.stage)}/")


def organize(photo):
    """Move a photo saved before this layout (or before its patient's name changed) into its folder."""
    if not photo.file or is_organized(photo) or not default_storage.exists(photo.file.name):
        return False
    old = photo.file.name
    with default_storage.open(old, "rb") as source:
        new = default_storage.save(default_storage.generate_filename(readable_path(photo, old)), source)
    type(photo).objects.filter(pk=photo.pk).update(file=new)
    photo.file.name = new
    default_storage.delete(old)
    return True


def photos_zip(patient, photos):
    """A ZIP file (open temporary file) with the patient's photos in the same folders."""
    archive = tempfile.TemporaryFile()
    base = patient_folder(patient)
    used = set()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as bundle:  # photos are compressed already
        for photo in photos:
            if not photo.file or not default_storage.exists(photo.file.name):
                continue
            ext = os.path.splitext(photo.file.name)[1].lower()
            name, number = f"{base}/{stage_folder(photo.stage)}/{file_title(photo)}", 1
            while f"{name}{ext}" in used:
                number += 1
                name = f"{base}/{stage_folder(photo.stage)}/{file_title(photo)} ({number})"
            used.add(f"{name}{ext}")
            with default_storage.open(photo.file.name, "rb") as source:
                bundle.writestr(f"{name}{ext}", source.read())
    archive.seek(0)
    return archive
