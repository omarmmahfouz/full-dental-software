"""Putting a checked paper file into the patient's file: the patient (a new file, or the empty fields of the patient
chosen; a different value replaces the old one only when ticked, and through the head's approval when the reception
asks), the medical and dental history (kept like a history taken at the reception, so the dentist starts from it),
and the pages, in order and upright, in the patient's documents (the ID card, the X-rays and the consents also in
their own places)."""

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.charting.forms import HISTORY_FIELDSETS, HISTORY_FIELDS

from .fields import BY_NAME, CONDITIONS, PATIENT, YES_NO
from .models import PaperFile, PaperPage
from .pages import clean_pdf

DENTAL_FIELDS = set(HISTORY_FIELDSETS[4][1])


def initial_values(paper):
    """(patient values, history values) for the review forms, from the values read."""
    patient, history = {}, {}
    for row in paper.fields.all():
        spec = BY_NAME.get(row.name)
        if spec is None or not row.value:
            continue
        if spec.kind == CONDITIONS:
            value = [int(pk) for pk in row.value.split(",") if pk.strip().isdigit()]
        elif spec.kind == YES_NO:
            value = row.value == "yes"
        else:
            value = row.value
        (patient if spec.part == PATIENT else history)[row.name] = value
    return patient, history


def _empty(value):
    return value in (None, "", "unknown") or (hasattr(value, "exists") and not value.exists())


def _filled(value):
    if hasattr(value, "__iter__") and not isinstance(value, str):
        return bool(list(value))
    return value not in (None, "", False)


def has_history(form):
    return any(_filled(form.cleaned_data.get(name)) for name in HISTORY_FIELDS)


@transaction.atomic
def approve(paper, user, patient_form=None, history_form=None, patient=None, replace=(), pages_only=False):
    """Save a checked paper file. ``patient``: the patient chosen (None = a new file from ``patient_form``).
    Returns (the patient, the change waiting for approval or None)."""
    from apps.core.approvals import needs_approval, request_change
    from apps.core.models import ChangeRequest
    from apps.patients.models import Patient

    waiting = None
    if pages_only:
        pass
    elif patient is None:
        patient = patient_form.save(commit=False)
        patient.branch, patient.created_by = paper.branch, user
        patient.save()
        patient_form.save_m2m()
    else:
        patient = Patient.objects.get(pk=patient.pk)  # as saved (the form changed its copy in memory)
        filled, changes = [], {}
        for name in patient_form.fields:
            model_name = "referred_by" if name == "referred_by_lookup" else name
            new = patient_form.cleaned_data.get(name)
            if not _filled(new):
                continue
            old = getattr(patient, model_name)
            if _empty(old):
                setattr(patient, model_name, new)
                filled.append(model_name)
            elif old != new and name in replace:
                changes[model_name] = new
        if filled:
            patient.save(update_fields=filled + ["updated_at"])
        if changes:
            if needs_approval(user):
                waiting = request_change(ChangeRequest.Kind.PATIENT, patient, changes, user,
                                         reason=_("From the old paper file %(name)s") % {"name": paper.original_name})
            else:
                for name, value in changes.items():
                    setattr(patient, name, value)
                patient.save(update_fields=list(changes) + ["updated_at"])
    if history_form is not None and not pages_only and has_history(history_form):
        _save_history(paper, patient, history_form, user)
    paper.document = file_documents(paper, patient, user)
    paper.patient, paper.status = patient, PaperFile.Status.APPROVED
    paper.approved_by, paper.approved_at, paper.error = user, timezone.now(), ""
    paper.save(update_fields=["document", "patient", "status", "approved_by", "approved_at", "error", "updated_at"])
    return patient, waiting


def _save_history(paper, patient, form, user):
    from apps.charting.sync import sync_medical_history

    history = form.save(commit=False)
    history.patient, history.history_only, history.created_by = patient, True, user
    history.exam_date = form.cleaned_data.get("exam_date") or patient.registered_on or timezone.localdate()
    values = {name for name in HISTORY_FIELDS if _filled(form.cleaned_data.get(name))}
    history.medical_taken = bool(values - DENTAL_FIELDS)
    history.dental_taken = bool(values & DENTAL_FIELDS)
    history.save()
    form.save_m2m()
    if patient.examinations.order_by("-exam_date", "-pk").first() == history:
        sync_medical_history(history)  # the newest history gives the file its list of diseases
    return history


def file_documents(paper, patient, user):
    """The pages kept in the patient's documents: the whole file in order (returned), and the ID card, the X-rays
    and the consents in their own places."""
    from apps.patients.models import PatientDocument

    pages = [page for page in paper.pages.all() if page.kind not in PaperPage.LEFT_OUT]
    pages.sort(key=lambda page: page.place_in_file)
    if not pages:
        return None
    note = _("Old paper file, read on %(day)s") % {"day": timezone.localdate().strftime("%d/%m/%Y")}
    whole = PatientDocument(patient=patient, kind=PatientDocument.Kind.OLD_FILE, notes=note[:255], created_by=user)
    whole.file.save("paper-file.pdf", ContentFile(clean_pdf(paper, pages)), save=False)
    whole.save()
    have = set(patient.documents.values_list("kind", flat=True))
    for kind in (PaperPage.Kind.ID_FRONT, PaperPage.Kind.ID_BACK):
        page = next((page for page in pages if page.kind == kind), None)
        if page is not None and kind not in have:
            page.image.open("rb")
            try:
                picture = ContentFile(page.image.read(), name=f"{kind}.jpg")
            finally:
                page.image.close()
            PatientDocument.objects.create(patient=patient, kind=kind, file=picture, created_by=user,
                                           notes=_("From the old paper file"))
    for page_kind, kind in ((PaperPage.Kind.XRAY, PatientDocument.Kind.XRAY),
                            (PaperPage.Kind.CONSENT, PatientDocument.Kind.CONSENT)):
        chosen = [page for page in pages if page.kind == page_kind]
        if chosen:
            document = PatientDocument(patient=patient, kind=kind, created_by=user, notes=_("From the old paper file"))
            document.file.save(f"{kind}.pdf", ContentFile(clean_pdf(paper, chosen)), save=False)
            document.save()
    return whole


def set_aside(paper, user):
    paper.status, paper.approved_by, paper.approved_at = PaperFile.Status.SET_ASIDE, user, timezone.now()
    paper.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])


def read_again(paper):
    """Forget the readings and read the file again (it costs again)."""
    from .models import PaperReading, PaperSettings

    readings = 2 if PaperSettings.get().two_readings else 1
    paper.fields.all().delete()
    PaperReading.objects.filter(page__file=paper).delete()
    pages = list(paper.pages.all())
    PaperReading.objects.bulk_create(
        PaperReading(page=page, number=number) for page in pages for number in range(1, readings + 1))
    PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.WAITING, error="", read_at=None,
                                                 suggested=None, suggested_reason="")
