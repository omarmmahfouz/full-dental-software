"""The patient's file at a clinic of specialists (El Khadem, round 16): not the steps of an implant case (CIA), but
the medical and dental history, then one tile for each specialty: what was done in it, when and by whom, and what is
still open (a root canal not finished, a TMJ follow-up...). Every specialty counts the same."""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.clinical.models import StepGroup, TreatmentStep

from .models import EndoCase, OrthoCase, ProsthoCase, ShadeRecord, TMJExam

# (code, label, icon, the kinds of treatment steps it holds, its chart and where a new one starts)
SECTIONS = [
    ("endo", _("Endodontics"), "bi-droplet-half", {StepGroup.ENDO}, "endo"),
    ("restorative", _("Restorative (fillings)"), "bi-circle-half", {StepGroup.FILLINGS}, None),
    ("prostho", _("Prosthodontics"), "bi-gem", {StepGroup.FIXED, StepGroup.REMOVABLE}, "prostho"),
    ("surgery", _("Oral surgery"), "bi-scissors", {StepGroup.SURGERY}, None),
    ("implants", _("Implants"), "bi-implant", {StepGroup.IMPLANT_SURGERY, StepGroup.IMPLANT_TEETH,
                                                 StepGroup.IMPLANT_CARE}, "implants"),
    ("gums", _("Periodontics"), "bi-stars", {StepGroup.GUMS}, None),
    ("tmj", _("TMJ"), "bi-activity", set(), "tmj"),
    ("ortho", _("Orthodontics"), "bi-arrows-collapse", {StepGroup.ORTHO}, "ortho"),
    ("pedo", _("Pediatric"), "bi-balloon-heart", {StepGroup.PEDO}, None),
]


def specialty_strip(patient):
    """[{code, label, icon, count, last (date), by (doctor), open (bool), url, start}] for the patient's file."""
    from apps.surgery.models import Surgery

    steps = list(TreatmentStep.objects.filter(patient=patient).select_related("step_type", "operator")
                 .order_by("-performed_at"))
    records = {
        "endo": list(EndoCase.objects.filter(patient=patient).select_related("dentist").order_by("-created_at")),
        "prostho": list(ProsthoCase.objects.filter(patient=patient).select_related("dentist").order_by("-created_at"))
        + list(ShadeRecord.objects.filter(patient=patient).select_related("dentist").order_by("-created_at")),
        "tmj": list(TMJExam.objects.filter(patient=patient).select_related("dentist").order_by("-created_at")),
        "ortho": list(OrthoCase.objects.filter(patient=patient).select_related("dentist").order_by("-created_at")),
        "implants": list(Surgery.objects.filter(patient=patient).select_related("operator_1").order_by("-date")),
    }
    starts = {
        "endo": reverse("specialties:endo_create") + f"?patient={patient.pk}",
        "prostho": reverse("specialties:prostho_create") + f"?patient={patient.pk}",
        "tmj": reverse("specialties:tmj_create") + f"?patient={patient.pk}",
        "ortho": reverse("specialties:ortho_create") + f"?patient={patient.pk}",
        "implants": reverse("surgery:create") + f"?patient={patient.pk}",
    }
    tiles = []
    for code, label, icon, groups, chart in SECTIONS:
        mine = [s for s in steps if s.step_type.group in groups]
        charts = records.get(chart, []) if chart else []
        dated = [(s.performed_at.date(), s.operator) for s in mine]
        for record in charts:
            when = getattr(record, "date", None) or record.created_at.date()
            dated.append((when, getattr(record, "dentist", None) or getattr(record, "operator_1", None)))
        dated.sort(key=lambda row: row[0], reverse=True)
        is_open = any(_is_open(record) for record in charts)
        url = ""
        if charts:
            url = charts[0].get_absolute_url()
        elif mine:
            url = reverse("patients:detail", args=[patient.pk]) + "#steps"
        tiles.append({
            "code": code, "label": label, "icon": icon, "count": len(mine) + len(charts),
            "last": dated[0][0] if dated else None, "by": dated[0][1] if dated else None, "open": is_open,
            "url": url, "start": starts.get(chart) or reverse("clinical:step_create") + f"?patient={patient.pk}",
        })
    return tiles


def _is_open(record):
    status = getattr(record, "status", "")
    if isinstance(record, EndoCase):
        return status != EndoCase.Status.OBTURATED
    if isinstance(record, OrthoCase):
        return status != OrthoCase.Status.FINISHED
    return False
