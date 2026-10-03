"""Round 13 sample data: packages of old paper files of CIA, as the Paper Reader makes them (``reader/``).

- One package was imported two days ago: a new patient read from her paper file (her data, the medical history and
  the scanned file as one PDF), and the pages only of a registered patient's file.
- One package was looked at but not imported yet: a registered patient's file that fills his empty job and replaces
  his second phone (that change waits for the head's approval when the reception imports it).

``make_package`` is also used by the tests."""

import io
import json
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from apps.core.models import Branch
from apps.dentists.models import Dentist
from apps.patients.models import MedicalCondition, ReferralSource

from . import importer
from .fields import PACKAGE_KIND, VERSION
from .models import PaperImport

HERE = Path(__file__).resolve().parent / "demo"


def scanned_pdf():
    """The two pages of the sample paper file as one PDF (the history page turned upright, as the reader does)."""
    first = Image.open(HERE / "page-1.jpg").convert("RGB")
    second = Image.open(HERE / "page-2.jpg").convert("RGB").transpose(Image.Transpose.ROTATE_270)
    output = io.BytesIO()
    first.save(output, "PDF", save_all=True, append_images=[second], resolution=150)
    return output.getvalue()


def entry(name, *, target="new", file_number="", patient=None, history=None, replace=(), pages_only=False,
          read_at=None, documents=None, token=None):
    """One file of a package: (its manifest entry, {path in the ZIP: bytes})."""
    token = token or uuid.uuid4().hex
    read_at = read_at or timezone.localtime()
    files = {f"files/{token}/{key}": data for key, data in (documents or {}).items()}
    row = {
        "token": token, "name": name, "pages": 2, "read_at": read_at.isoformat(),
        "approved_at": (read_at + timedelta(hours=1)).isoformat(), "approved_by": "secretary",
        "target": target, "file_number": file_number, "patient": patient or {}, "history": history or {},
        "replace": list(replace), "pages_only": pages_only,
        "documents": {key.rsplit(".", 1)[0]: f"files/{token}/{key}" for key in (documents or {})},
    }
    return row, files


def make_package(place_code, entries, made_by="secretary"):
    """A package as the Paper Reader makes it (the bytes of the ZIP)."""
    manifest = {"kind": PACKAGE_KIND, "version": VERSION, "place": place_code,
                "lists_made_at": timezone.localtime().isoformat(), "made_at": timezone.localtime().isoformat(),
                "made_by": made_by, "files": []}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for row, files in entries:
            for path, data in files.items():
                package.writestr(path, data, compress_type=zipfile.ZIP_STORED)
            manifest["files"].append(row)
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return output.getvalue()


def bring_in(place, name, data, user, when=None):
    """A package brought in (looked at, not imported yet)."""
    upload = io.BytesIO(data)
    paper_import = PaperImport(branch=place, name=name, manifest=importer.read_manifest(upload), created_by=user)
    paper_import.package.save("package.zip", ContentFile(data), save=False)
    paper_import.save()
    if when is not None:
        PaperImport.objects.filter(pk=paper_import.pk).update(created_at=when)
    return paper_import


def _samia(read_at):
    facebook = ReferralSource.objects.filter(name_en="Facebook").values_list("pk", flat=True).first()
    mona = Dentist.objects.filter(full_name="Dr. Mona Refaat").values_list("pk", flat=True).first()
    conditions = ",".join(str(pk) for pk in MedicalCondition.objects.filter(
        name_en__in=("Diabetes", "High blood pressure")).order_by("sort_order", "pk").values_list("pk", flat=True))
    patient = {"full_name": "سامية عبد الرحمن محمود", "national_id": "28807222103468", "birth_date": "22/07/1988",
               "gender": "F", "governorate": "21", "phone_primary": "01145567781", "city": "الدقي",
               "address": "12 شارع التحرير، الدقي", "registered_on": "12/09/2017"}
    if facebook:
        patient["referral_source"] = str(facebook)
    history = {"exam_date": "12/09/2017", "bp_last_systolic": "140", "bp_last_diastolic": "90",
               "bp_last_when": "last month", "hba1c": "8.2", "allergy_penicillin": "yes",
               "drugs_taken": "Glucophage 1000, Concor 5", "smoker": "no", "bruxism": "at night"}
    if mona:
        history["examined_by"] = str(mona)
    if conditions:
        history["conditions"] = conditions
    return entry("CIA old file 2017 - Samia Abdelrahman.pdf", patient=patient, history=history, read_at=read_at,
                 documents={"file.pdf": scanned_pdf()})


def load_papers(patients, secretary):
    place = Branch.objects.get(code="CIA")
    now = timezone.localtime()
    registered = [p for p in patients if p.branch_id == place.pk]
    # Imported two days ago: a new patient, and the pages only of a registered patient's file.
    rows = [_samia(now - timedelta(days=2, hours=3))]
    if registered:
        kept = registered[0]
        rows.append(entry(f"Old file {kept.file_number}.pdf", target="existing", file_number=kept.file_number,
                          pages_only=True, read_at=now - timedelta(days=2, hours=3),
                          documents={"file.pdf": scanned_pdf()}))
    done = bring_in(place, f"paper-files-CIA-{now - timedelta(days=2):%Y-%m-%d}-1030.zip", make_package("CIA", rows),
                    secretary, when=now - timedelta(days=2))
    importer.run(done, place, secretary)
    PaperImport.objects.filter(pk=done.pk).update(imported_at=now - timedelta(days=2))
    # Looked at, not imported yet: fills the job of a registered patient and replaces his second phone.
    later = next((p for p in registered[1:] if not p.occupation), None)
    if later is not None:
        row = entry(f"Old file {later.file_number}.pdf", target="existing", file_number=later.file_number,
                    patient={"occupation": "مدرس", "phone_secondary": "01223344556"}, replace=["phone_secondary"],
                    read_at=now - timedelta(hours=5), documents={"file.pdf": scanned_pdf()})
        bring_in(place, f"paper-files-CIA-{now:%Y-%m-%d}-0915.zip", make_package("CIA", [row]), secretary)
