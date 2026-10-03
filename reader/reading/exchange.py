"""The two files that link the Paper Reader with the dental system (no network between them):

- the **lists file** (JSON) made by the dental system: the place, the values to read (names, kinds, labels, choices)
  and the place's registered patients, brought in here (Settings → Lists from the system);
- the **package** (ZIP) made here of the approved files: ``manifest.json`` with the values approved for each file,
  and its documents (the whole file as one clean PDF, the ID card, the X-rays, the consents) under
  ``files/<token>/``; the dental system imports it (Old paper files → Import a package) and checks everything again.
"""

import io
import json
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Export, KnownPatient, PaperFile, PaperPage, SystemLists
from .pages import clean_pdf

LISTS_KIND, PACKAGE_KIND, VERSION = "cia-paper-reader-lists", "cia-paper-reader-package", 1
# A package stays under what the clinic server takes in one upload (320 MB); the files left go in the next package.
PACKAGE_MB = 250


@transaction.atomic
def import_lists(data, user=None):
    """Bring in a lists file (a dict). Returns (the place's code, the number of values, of patients)."""
    if not isinstance(data, dict) or data.get("kind") != LISTS_KIND:
        raise ValidationError(_("This is not a lists file of the dental system."))
    if data.get("version") != VERSION:
        raise ValidationError(_("This lists file is from another version of the dental system: update both."))
    fields = data.get("fields")
    place = data.get("place") or {}
    if not isinstance(fields, list) or not fields or not place.get("code"):
        raise ValidationError(_("This lists file is not complete."))
    patients = data.pop("patients", []) or []
    lists = SystemLists.get()
    lists.data, lists.place_code = data, str(place["code"])[:10]
    lists.imported_at, lists.imported_by = timezone.now(), user
    lists.save()
    KnownPatient.objects.all().delete()
    KnownPatient.objects.bulk_create([KnownPatient(
        file_number=str(row.get("file_number", ""))[:20], full_name=str(row.get("full_name", ""))[:150],
        national_id=str(row.get("national_id", ""))[:20], phone_primary=str(row.get("phone_primary", ""))[:20],
        phone_secondary=str(row.get("phone_secondary", ""))[:20], values=row.get("values") or {},
    ) for row in patients if row.get("file_number")], batch_size=500)
    return lists.place_code, len(fields), KnownPatient.objects.count()


def _read(field_file):
    field_file.open("rb")
    try:
        return field_file.read()
    finally:
        field_file.close()


def documents(paper):
    """{name in the package: bytes} of a file's documents."""
    pages = sorted((page for page in paper.pages.all() if page.kind not in PaperPage.LEFT_OUT),
                   key=lambda page: page.place_in_file)
    out = {}
    if pages:
        out["file.pdf"] = clean_pdf(paper, pages)
    for kind in (PaperPage.Kind.ID_FRONT, PaperPage.Kind.ID_BACK):
        page = next((page for page in pages if page.kind == kind), None)
        if page is not None:
            out[f"{kind}.jpg"] = _read(page.image)
    for kind in (PaperPage.Kind.XRAY, PaperPage.Kind.CONSENT):
        chosen = [page for page in pages if page.kind == kind]
        if chosen:
            out[f"{kind}.pdf"] = clean_pdf(paper, chosen)
    return out


def build_package(papers, user, limit_mb=PACKAGE_MB):
    """Make one package of approved files (in order, until it reaches ``limit_mb``); returns the Export (its ZIP is
    kept here too). The files that did not fit stay approved for the next package."""
    lists = SystemLists.get()
    now = timezone.localtime()
    manifest = {"kind": PACKAGE_KIND, "version": VERSION, "place": lists.place_code,
                "lists_made_at": lists.data.get("made_at", ""), "made_at": now.isoformat(),
                "made_by": user.get_username() if user else "", "files": []}
    output = io.BytesIO()
    packed = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for paper in papers:
            if packed and output.tell() > limit_mb * 1024 * 1024:
                break
            packed.append(paper)
            approved = paper.approved or {}
            entry = {
                "token": paper.token, "name": paper.original_name, "pages": paper.page_count,
                "read_at": paper.read_at.isoformat() if paper.read_at else "",
                "approved_at": paper.approved_at.isoformat() if paper.approved_at else "",
                "approved_by": paper.approved_by.get_username() if paper.approved_by else "",
                "target": approved.get("target", "new"), "file_number": approved.get("file_number", ""),
                "patient": approved.get("patient", {}), "history": approved.get("history", {}),
                "replace": approved.get("replace", []), "pages_only": bool(approved.get("pages_only")),
                "documents": {},
            }
            for name, data in documents(paper).items():
                path = f"files/{paper.token}/{name}"
                package.writestr(path, data, compress_type=zipfile.ZIP_STORED)  # PDFs and JPEGs are packed already
                entry["documents"][name.rsplit(".", 1)[0]] = path
            manifest["files"].append(entry)
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    name = f"paper-files-{lists.place_code}-{now:%Y-%m-%d-%H%M}.zip"
    export = Export(made_by=user, place_code=lists.place_code, name=name, count=len(manifest["files"]))
    export.package.save(name, ContentFile(output.getvalue()), save=False)
    export.save()
    PaperFile.objects.filter(pk__in=[paper.pk for paper in packed]).update(
        status=PaperFile.Status.EXPORTED, exported_in=export)
    return export
