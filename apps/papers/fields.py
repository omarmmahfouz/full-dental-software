"""What is read from an old paper file: the patient's data (the registration form and the ID card) and the medical
and dental history (pages 1-2 of the CIA paper chart). Each value has a kind, so its answer can be checked and put
into the same form the reception and the dentists use (round 13, first part; the teeth, the plan, the visits and the
payments come in the second part)."""

from dataclasses import dataclass, field

from django.db import models
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from apps.charting.forms import HISTORY_FIELDS
from apps.charting.models import Examination
from apps.core.utils import EGYPT_GOVERNORATES
from apps.patients.models import Patient

# Kinds of values: how an answer is cleaned and checked (checks.py).
TEXT, NAME, NATIONAL_ID, PHONE, DATE, CHOICE, YES_NO, NUMBER, DECIMAL, CONDITIONS, DENTIST, REFERRAL = (
    "text", "name", "national_id", "phone", "date", "choice", "yes_no", "number", "decimal", "conditions", "dentist",
    "referral")

PATIENT, HISTORY = "patient", "history"

PATIENT_FIELDS = [
    "full_name", "national_id", "birth_date", "gender", "marital_status", "occupation", "phone_primary",
    "phone_secondary", "governorate", "city", "address", "missing_teeth", "missing_teeth_notes", "medical_notes",
    "referral_source", "referral_notes", "registered_on", "notes",
]
# The history page also says when it was taken and by whom.
HISTORY_HEAD = ["exam_date", "examined_by"]

# Readings outside these limits are marked for checking (a 7 read as a 1, a missing digit...).
RANGES = {
    "bp_last_systolic": (60, 260), "bp_clinic_systolic": (60, 260),
    "bp_last_diastolic": (30, 160), "bp_clinic_diastolic": (30, 160),
    "glucose_last": (30, 700), "glucose_random_clinic": (30, 700),
    "hba1c": (3, 20), "cigarettes_per_day": (0, 120),
    "cooperation_score": (0, 10), "implant_willingness_score": (0, 10),
}
# Where each value is usually written (the page it is taken from when it is on several pages).
BEST_PAGE = {
    "full_name": ("id_front", "registration"), "national_id": ("id_front", "registration"),
    "birth_date": ("id_front", "registration"), "address": ("id_front", "registration"),
    "gender": ("id_back", "registration"), "marital_status": ("id_back", "registration"),
    "occupation": ("id_back", "registration"),
}
# Words the paper may use for yes and no.
YES = {"yes", "y", "true", "1", "+", "✓", "✔", "x", "نعم", "ايوه", "أيوه", "اه", "positive", "pos", "+ve"}
NO = {"no", "n", "false", "0", "-", "لا", "negative", "neg", "-ve", "nil", "none", "لا يوجد"}


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
    """The English and the Arabic words for a label or a choice (the paper may be in either language)."""
    with translation.override("en"):
        english = str(text)
    with translation.override("ar"):
        arabic = str(text)
    return english, arabic


def choices_of(spec):
    """[(code, [words...])] for a value chosen from a list: the codes and the words the paper may use."""
    from apps.dentists.models import Dentist
    from apps.patients.models import MedicalCondition, ReferralSource

    if spec.kind == CHOICE and spec.name == "governorate":
        return [(code, list(labels(label))) for code, label in EGYPT_GOVERNORATES.items()]
    if spec.kind == CHOICE:
        return [(code, [code, *labels(label)]) for code, label in spec.choices]
    if spec.kind == REFERRAL:
        rows = ReferralSource.objects.filter(is_active=True).order_by("sort_order", "pk")
        return [(str(row.pk), [row.name_en, row.name_ar]) for row in rows]
    if spec.kind == CONDITIONS:
        rows = MedicalCondition.objects.filter(is_active=True).order_by("sort_order", "pk")
        return [(str(row.pk), [row.name_en, row.name_ar]) for row in rows]
    if spec.kind == DENTIST:
        rows = Dentist.objects.filter(is_active=True).order_by("full_name", "pk")
        return [(str(row.pk), [row.full_name]) for row in rows]
    return []
