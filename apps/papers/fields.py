"""What the Paper Reader reads from an old paper file, described from the system's own forms and lists: the
patient's data (the registration form and the ID card) and the medical and dental history (pages 1-2 of the CIA
paper chart). ``lists_file(place)`` is the file the reader brings in (Old paper files → Lists for the reader): each
value's name, kind, labels in English and Arabic, section, choices and usual range, and the place's registered
patients, so the reader finds whose file a paper file is. Round 13, first part; the teeth, the plan, the visits and
the payments come in the second part."""

from dataclasses import dataclass, field

from django.db import models
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _

from apps.charting.forms import HISTORY_FIELDS
from apps.charting.models import Examination
from apps.core.utils import EGYPT_GOVERNORATES
from apps.patients.models import Patient

LISTS_KIND, PACKAGE_KIND, VERSION = "cia-paper-reader-lists", "cia-paper-reader-package", 1

# Kinds of values: how the reader cleans and checks an answer, and how the import reads it back.
TEXT, NAME, NATIONAL_ID, PHONE, DATE, CHOICE, YES_NO, NUMBER, DECIMAL, CONDITIONS, DENTIST, REFERRAL = (
    "text", "name", "national_id", "phone", "date", "choice", "yes_no", "number", "decimal", "conditions", "dentist",
    "referral")
PATIENT, HISTORY = "patient", "history"

PATIENT_FIELDS = [
    "full_name", "national_id", "birth_date", "gender", "marital_status", "occupation", "phone_primary",
    "phone_secondary", "governorate", "city", "address", "missing_teeth", "missing_teeth_notes", "medical_notes",
    "referral_source", "referral_notes", "registered_on", "notes",
]
# Readings outside these limits are marked for checking (a 7 read as a 1, a missing digit...).
RANGES = {
    "bp_last_systolic": (60, 260), "bp_clinic_systolic": (60, 260),
    "bp_last_diastolic": (30, 160), "bp_clinic_diastolic": (30, 160),
    "glucose_last": (30, 700), "glucose_random_clinic": (30, 700),
    "hba1c": (3, 20), "cigarettes_per_day": (0, 120),
    "cooperation_score": (0, 10), "implant_willingness_score": (0, 10),
}


@dataclass
class Spec:
    name: str
    part: str
    kind: str
    label: object
    model_field: object = None
    choices: list = field(default_factory=list)


def _kind_of(model_field):
    if model_field.many_to_many:
        return CONDITIONS
    if isinstance(model_field, models.BooleanField):
        return YES_NO
    if model_field.choices:
        return CHOICE
    if isinstance(model_field, models.DecimalField):
        return DECIMAL
    if isinstance(model_field, (models.PositiveSmallIntegerField, models.IntegerField)):
        return NUMBER
    if isinstance(model_field, models.DateField):
        return DATE
    return TEXT


PATIENT_KINDS = {"full_name": NAME, "national_id": NATIONAL_ID, "phone_primary": PHONE, "phone_secondary": PHONE,
                 "referral_source": REFERRAL}


def _build():
    specs = []
    for name in PATIENT_FIELDS:
        model_field = Patient._meta.get_field(name)
        kind = PATIENT_KINDS.get(name) or _kind_of(model_field)
        specs.append(Spec(name, PATIENT, kind, model_field.verbose_name, model_field, list(model_field.choices or [])))
    exam = Examination._meta
    specs.append(Spec("exam_date", HISTORY, DATE, _("date the history was taken"), exam.get_field("exam_date")))
    specs.append(Spec("examined_by", HISTORY, DENTIST, _("taken by (the dentist)"), exam.get_field("examined_by")))
    for name in HISTORY_FIELDS:
        model_field = exam.get_field(name)
        specs.append(Spec(name, HISTORY, _kind_of(model_field), model_field.verbose_name, model_field,
                          list(model_field.choices or [])))
    return specs


SPECS = _build()
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = [spec.name for spec in SPECS]


def labels(text):
    """The English and the Arabic words for a label or a choice."""
    with translation.override("en"):
        english = str(text)
    with translation.override("ar"):
        arabic = str(text)
    return english, arabic


def choices_of(spec, place=None):
    """[(code, english, arabic)] for a value chosen from a list."""
    from apps.dentists.models import Dentist
    from apps.patients.models import MedicalCondition, ReferralSource

    if spec.kind == CHOICE and spec.name == "governorate":
        return [(code, *labels(label)) for code, label in EGYPT_GOVERNORATES.items()]
    if spec.kind == CHOICE:
        return [(code, *labels(label)) for code, label in spec.choices]
    if spec.kind == REFERRAL:
        rows = ReferralSource.objects.filter(is_active=True).order_by("sort_order", "pk")
        return [(str(row.pk), row.name_en, row.name_ar) for row in rows]
    if spec.kind == CONDITIONS:
        rows = MedicalCondition.objects.filter(is_active=True).order_by("sort_order", "pk")
        return [(str(row.pk), row.name_en, row.name_ar) for row in rows]
    if spec.kind == DENTIST:
        rows = Dentist.objects.filter(is_active=True).working_at(place).order_by("full_name", "pk")
        return [(str(row.pk), row.full_name, row.full_name) for row in rows]
    return []


LONG = {"medical_notes", "notes", "medical_comment", "conditions_comment", "drugs_taken", "operator_comments"}


def text_of(patient, name):
    """A patient's value as the reader writes values (dates dd/mm/yyyy, a choice's code, a list's number)."""
    value = getattr(patient, f"{name}_id", None) if name in ("referral_source",) else getattr(patient, name, None)
    if value in (None, ""):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def lists_file(place):
    """The lists file for the Paper Reader (a dict, saved as JSON)."""
    from .forms import PaperHistoryForm, PaperPatientForm

    sections = {}
    for form in (PaperPatientForm, PaperHistoryForm):
        for title, names in form.fieldsets:
            for name in names:
                sections.setdefault(name, title)
    with translation.override("en"):  # the forms' own rules for a new patient (required fields)
        form = PaperPatientForm(instance=Patient(branch=place))
        required = {name for name, form_field in form.fields.items() if form_field.required and name in PATIENT_FIELDS
                    and not Patient._meta.get_field(name).has_default()}
    rows = []
    for spec in SPECS:
        label_en, label_ar = labels(spec.label)
        section_en, section_ar = labels(sections.get(spec.name, "")) if sections.get(spec.name) else ("", "")
        rows.append({
            "name": spec.name, "part": spec.part, "kind": spec.kind, "label_en": label_en, "label_ar": label_ar,
            "section_en": section_en, "section_ar": section_ar, "required": spec.name in required,
            "long": spec.name in LONG, "choices": [list(choice) for choice in choices_of(spec, place)],
            "range": list(RANGES[spec.name]) if spec.name in RANGES else None,
        })
    patients = []
    for patient in Patient.objects.filter(branch=place).order_by("pk").iterator(chunk_size=500):
        patients.append({
            "file_number": patient.file_number, "full_name": patient.full_name, "national_id": patient.national_id,
            "phone_primary": patient.phone_primary, "phone_secondary": patient.phone_secondary,
            "values": {name: text for name in PATIENT_FIELDS if (text := text_of(patient, name))},
        })
    name_en, name_ar = place.name_en or place.name_ar, place.name_ar
    return {"kind": LISTS_KIND, "version": VERSION, "made_at": timezone.localtime().isoformat(),
            "place": {"code": place.code, "badge": place.badge, "name_en": name_en, "name_ar": name_ar},
            "fields": rows, "patients": patients}
