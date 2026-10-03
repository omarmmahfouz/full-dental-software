"""Importing a package of the Paper Reader (Old paper files → Import a package). The package is a ZIP with
``manifest.json`` (the approved values of each file) and the documents of each file under ``files/<token>/``.

Nothing is trusted: every value is checked again with the registration form (``PaperPatientForm``) and the history
form (``PaperHistoryForm``), as if typed at the desk; each file is saved on its own (one bad file does not stop the
others) and only once (by its token). Into a registered patient only the empty fields are filled; a value marked
"replace" in the reader changes the file directly for the heads, and through their approval for the reception."""

import json
import re
import zipfile
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.charting.forms import HISTORY_FIELDSETS, HISTORY_FIELDS
from apps.patients.models import Patient, PatientDocument

from .fields import BY_NAME, CONDITIONS, PACKAGE_KIND, PATIENT_FIELDS, VERSION, YES_NO
from .forms import PaperHistoryForm, PaperPatientForm
from .models import ImportedFile, PaperImport

MANIFEST_MB = 20
DOCUMENT_MB = 300
TOKEN = re.compile(r"^[0-9a-f]{32}$")
# The documents a file may bring, and where each goes in the patient's documents.
DOCUMENTS = {
    "file": (".pdf", PatientDocument.Kind.OLD_FILE),
    "id_front": (".jpg", PatientDocument.Kind.ID_FRONT),
    "id_back": (".jpg", PatientDocument.Kind.ID_BACK),
    "xray": (".pdf", PatientDocument.Kind.XRAY),
    "consent": (".pdf", PatientDocument.Kind.CONSENT),
}
SIGNATURES = {".pdf": lambda head: b"%PDF" in head[:1024], ".jpg": lambda head: head.startswith(b"\xff\xd8\xff")}
DENTAL_FIELDS = set(HISTORY_FIELDSETS[4][1])


class PackageProblem(Exception):
    """The whole package cannot be used."""


class FileProblem(Exception):
    """One file of the package cannot be imported (the reason is shown)."""


# ------------------------------------------------------------------------------------------- the package
def read_manifest(package):
    """The package's contents (checked), from a ZIP file object."""
    try:
        archive = zipfile.ZipFile(package)
    except (zipfile.BadZipFile, OSError) as error:
        raise PackageProblem(_("This is not a package of the Paper Reader (a .zip file).")) from error
    with archive:
        try:
            info = archive.getinfo("manifest.json")
        except KeyError as error:
            raise PackageProblem(_("This is not a package of the Paper Reader (a .zip file).")) from error
        if info.file_size > MANIFEST_MB * 1024 * 1024:
            raise PackageProblem(_("This package is not complete."))
        try:
            manifest = json.loads(archive.read(info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise PackageProblem(_("This package is not complete.")) from error
        if not isinstance(manifest, dict) or manifest.get("kind") != PACKAGE_KIND:
            raise PackageProblem(_("This is not a package of the Paper Reader (a .zip file)."))
        if manifest.get("version") != VERSION:
            raise PackageProblem(_("This package is from another version of the Paper Reader: update both."))
        files = manifest.get("files")
        if not isinstance(files, list):
            raise PackageProblem(_("This package is not complete."))
        names = set(archive.namelist())
        for entry in files:
            if not isinstance(entry, dict) or not TOKEN.match(str(entry.get("token", ""))):
                raise PackageProblem(_("This package is not complete."))
            token = entry["token"]
            for key, path in (entry.get("documents") or {}).items():
                ext = DOCUMENTS.get(key, (None,))[0]
                if ext is None or path != f"files/{token}/{key}{ext}" or path not in names:
                    raise PackageProblem(_("This package is not complete."))
    return manifest


def plan(paper_import, place):
    """What will happen to each file: [{entry, patient, new, skip, problem}]."""
    rows = []
    for entry in paper_import.files:
        row = {"entry": entry, "patient": None, "new": False, "skip": False, "problem": "", "note": ""}
        if ImportedFile.objects.filter(token=entry["token"], status=ImportedFile.Status.IMPORTED).exists():
            row["skip"] = True
        else:
            try:
                row["patient"], row["new"], row["note"] = _whose(entry, place)
            except FileProblem as problem:
                row["problem"] = str(problem)
        rows.append(row)
    return rows


def _whose(entry, place):
    """(the registered patient or None, a new file?, a note) for one file."""
    patients = Patient.objects.filter(branch=place)
    if entry.get("target") == "existing":
        patient = patients.filter(file_number__iexact=str(entry.get("file_number", ""))).first()
        if patient is None:
            raise FileProblem(_("There is no file %(file)s at this place.") % {"file": entry.get("file_number", "")})
        return patient, False, ""
    if entry.get("pages_only"):
        raise FileProblem(_("Pages only, but no patient was chosen."))
    national_id = (entry.get("patient") or {}).get("national_id", "")
    patient = patients.filter(national_id=national_id).first() if national_id else None
    if patient is not None:
        return patient, False, _("Already registered (the same national ID): only its empty fields are filled.")
    return None, True, ""


# ------------------------------------------------------------------------------------------- one file
def _data(values, part):
    """The values of the reader as a form sends them."""
    data = {}
    for name, value in (values or {}).items():
        spec = BY_NAME.get(name)
        if spec is None or spec.part != part or value in (None, ""):
            continue
        if spec.kind == YES_NO:
            if value == "yes":
                data[name] = "on"
        elif spec.kind == CONDITIONS:
            data[name] = [code for code in str(value).split(",") if code.strip()]
        else:
            data[name] = str(value)
    return data


def current_data(form):
    """What an unchanged form of a saved patient sends."""
    data = {}
    for bound in form:
        value = bound.value()
        if isinstance(value, bool):
            if value:
                data[bound.name] = "on"
        elif isinstance(value, (list, tuple)):
            data[bound.name] = [str(item) for item in value]
        elif value is not None:
            data[bound.name] = value.strftime("%d/%m/%Y") if hasattr(value, "strftime") else str(value)
    return data


def _errors(form):
    lines = []
    for name, errors in form.errors.items():
        label = form.fields[name].label if name in form.fields else ""
        lines += [f"{label}: {error}" if label else str(error) for error in errors]
    return " ".join(lines)


def _empty(value):
    return value in (None, "", "unknown")


def _new_patient(entry, place, user):
    data = _data(entry.get("patient"), "patient")
    data.setdefault("id_type", Patient.IdType.NATIONAL_ID if re.fullmatch(r"\d{14}", data.get("national_id", ""))
                    else Patient.IdType.PASSPORT)
    data.setdefault("missing_teeth", "unknown")
    form = PaperPatientForm(data, instance=Patient(branch=place))
    if not form.is_valid():
        raise FileProblem(_errors(form))
    patient = form.save(commit=False)
    patient.branch, patient.created_by = place, user
    patient.save()
    form.save_m2m()
    return patient


def _fill_patient(entry, patient, user):
    """Fill the empty fields of a registered patient; a value marked "replace" changes it (or asks the head).
    Returns (how many filled, the change waiting for approval or None)."""
    from apps.core.approvals import needs_approval, request_change
    from apps.core.models import ChangeRequest

    values = _data(entry.get("patient"), "patient")
    replace = set(entry.get("replace") or [])
    data = current_data(PaperPatientForm(instance=patient))
    taken = {name: value for name, value in values.items()
             if name in PATIENT_FIELDS and (_empty(getattr(patient, name, None)) or name in replace)}
    if not taken:
        return 0, None
    data.update(taken)
    form = PaperPatientForm(data, instance=patient)
    if not form.is_valid():
        raise FileProblem(_errors(form))
    saved = Patient.objects.get(pk=patient.pk)  # as saved (the form changed its copy in memory)
    filled, changes = [], {}
    for name in taken:
        new, old = form.cleaned_data.get(name), getattr(saved, name)
        if _empty(old):
            setattr(saved, name, new)
            filled.append(name)
        elif new != old:
            changes[name] = new
    if filled:
        saved.save(update_fields=filled + ["updated_at"])
    waiting = None
    if changes:
        if needs_approval(user):
            waiting = request_change(ChangeRequest.Kind.PATIENT, saved, changes, user,
                                     reason=_("From the old paper file %(name)s") % {"name": entry.get("name", "")})
        else:
            for name, value in changes.items():
                setattr(saved, name, value)
            saved.save(update_fields=list(changes) + ["updated_at"])
    return len(filled), waiting


def _history(entry, patient, user):
    from apps.charting.sync import sync_medical_history

    data = _data(entry.get("history"), "history")
    if not any(name in data for name in HISTORY_FIELDS):
        return None
    form = PaperHistoryForm(data)
    if not form.is_valid():
        raise FileProblem(_errors(form))
    history = form.save(commit=False)
    history.patient, history.history_only, history.created_by = patient, True, user
    history.exam_date = form.cleaned_data.get("exam_date") or patient.registered_on or timezone.localdate()
    names = {name for name in HISTORY_FIELDS if name in data}
    history.medical_taken, history.dental_taken = bool(names - DENTAL_FIELDS), bool(names & DENTAL_FIELDS)
    history.save()
    form.save_m2m()
    if patient.examinations.order_by("-exam_date", "-pk").first() == history:
        sync_medical_history(history)  # the newest history gives the file its list of diseases
    return history


def _documents(archive, entry, patient, user):
    have = set(patient.documents.values_list("kind", flat=True))
    try:
        day = datetime.fromisoformat(entry.get("read_at") or "").date()
    except ValueError:
        day = timezone.localdate()
    note = _("Old paper file, read on %(day)s") % {"day": day.strftime("%d/%m/%Y")}
    checked = []  # every document is checked before any is saved
    for key, path in (entry.get("documents") or {}).items():
        ext, kind = DOCUMENTS[key]
        if kind in PatientDocument.CARD_KINDS and kind in have:
            continue  # the ID card already in the file stays
        info = archive.getinfo(path)
        if info.file_size > DOCUMENT_MB * 1024 * 1024:
            raise FileProblem(_("A document of this file is too large."))
        data = archive.read(info)
        if not SIGNATURES[ext](data[:1024]):
            raise FileProblem(_("A document of this file is not a real PDF or picture."))
        checked.append((key, ext, kind, data))
    for key, ext, kind, data in checked:
        document = PatientDocument(patient=patient, kind=kind, created_by=user,
                                   notes=(note if key == "file" else _("From the old paper file"))[:255])
        document.file.save(f"{key}{ext}", ContentFile(data), save=False)
        document.save()
    return len(checked)


def import_file(archive, entry, place, user, paper_import):
    """Import one file of the package; returns its ImportedFile."""
    token = entry["token"]
    record = ImportedFile(paper_import=paper_import, token=token, name=str(entry.get("name", ""))[:255])
    if ImportedFile.objects.filter(token=token, status=ImportedFile.Status.IMPORTED).exists():
        record.status = ImportedFile.Status.SKIPPED
        record.save()
        return record
    try:
        with transaction.atomic():
            patient, new, note = _whose(entry, place)
            notes = [note] if note else []
            waiting = None
            if new:
                patient = _new_patient(entry, place, user)
                notes.append(_("A new file was opened."))
            elif not entry.get("pages_only"):
                filled, waiting = _fill_patient(entry, patient, user)
                if filled:
                    notes.append(_("%(n)s empty fields were filled.") % {"n": filled})
                if waiting is not None:
                    notes.append(_("The values that replace the old ones wait for the head's approval."))
            if not entry.get("pages_only") and _history(entry, patient, user) is not None:
                notes.append(_("The medical and dental history was added."))
            if _documents(archive, entry, patient, user):
                notes.append(_("The scanned pages were kept in the documents."))
            record.status, record.patient, record.new_patient, record.change = (
                ImportedFile.Status.IMPORTED, patient, new, waiting)
            record.message = " ".join(str(note) for note in notes)
            record.save()
    except FileProblem as problem:
        record.status, record.message = ImportedFile.Status.FAILED, str(problem)[:2000]
        record.save()
    return record


def run(paper_import, place, user):
    """Import every file of a package that was looked at; the package's ZIP is then removed."""
    paper_import.package.open("rb")
    try:
        with zipfile.ZipFile(paper_import.package) as archive:
            results = [import_file(archive, entry, place, user, paper_import) for entry in paper_import.files]
    finally:
        paper_import.package.close()
    PaperImport.objects.filter(pk=paper_import.pk).update(status=PaperImport.Status.DONE, imported_at=timezone.now(),
                                                          imported_by=user)
    paper_import.drop_package()
    return results
