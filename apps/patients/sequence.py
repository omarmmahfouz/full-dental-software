"""The journey of a new patient's file, in the order the dentist works (round 10):

1. the medical history with the readings of the day (random blood sugar, blood pressure),
2. the dental history and habits (smoking...),
3. the dental examination (gloves on: missing, filled...),
4. the primary impression or diagnostic scan,
5. the CBCT (taken here, or asked from a centre),
6. the planning on the CBCT, the chart checked again, and the treatment plan (implants first, then the rest),
7. fit for surgery? (only when the readings or a disease need a physician's opinion, medical.py),
8. the surgery (chart, prescription, instructions, the follow-up visit),
9. the restorative work (only when the plan has it),
10. the delivery of the teeth on the implants (only when there are prostheses).

The patient's page shows the steps with the next one to do; a step opened from there ("flow") goes on to the next
one when it is saved, up to the plan. The impression and the CBCT may be skipped: a later step done passes them."""

from django.db.models import Count, Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

STEPS = [
    ("medical", _("Medical history and readings"), "bi-heart-pulse"),
    ("dental", _("Dental history and habits"), "bi-chat-square-text"),
    ("exam", _("Dental examination"), "bi-clipboard2-pulse"),
    ("impression", _("Impression or diagnostic scan"), "bi-upc-scan"),
    ("cbct", _("CBCT"), "bi-radioactive"),
    ("plan", _("Planning and treatment plan"), "bi-list-check"),
    ("fitness", _("Fit for surgery"), "bi-envelope-paper-heart"),
    ("surgery", _("Surgery"), "bi-implant"),
    ("restorative", _("Restorative work"), "bi-droplet-half"),
    ("delivery", _("Delivery on the implants"), "bi-bricks"),
]
CODES = [code for code, _label, _icon in STEPS]
FLOW = ["medical", "dental", "exam", "impression", "cbct", "plan"]  # one after the other on the first days
SKIPPABLE = {"impression", "cbct"}


def step_url(patient, code, flow=True):
    url = {
        "medical": reverse("patients:medical_history", args=[patient.pk]) + "?part=medical",
        "dental": reverse("patients:medical_history", args=[patient.pk]) + "?part=dental",
        "exam": reverse("charting:exam_create", args=[patient.pk]),
        "impression": reverse("patients:records", args=[patient.pk]) + "?step=impression",
        "cbct": reverse("patients:records", args=[patient.pk]) + "?step=cbct",
        "plan": reverse("charting:plan_create", args=[patient.pk]),
        "fitness": reverse("patients:consult_create", args=[patient.pk]),
        "surgery": reverse("surgery:create") + f"?patient={patient.pk}",
        "restorative": reverse("clinical:step_create") + f"?patient={patient.pk}",
        "delivery": reverse("charting:chart", args=[patient.pk]),
    }[code]
    if flow and code in FLOW:
        url += ("&" if "?" in url else "?") + "flow=1"
    return url


def _state(patient):
    """What is done in the file: {code: True/False}, plus notes shown under some steps."""
    from apps.clinical.models import TreatmentStepType
    from apps.surgery.models import Prosthesis

    from .medical import clearance

    exams = patient.examinations.aggregate(
        medical=Count("pk", filter=Q(medical_taken=True)), dental=Count("pk", filter=Q(dental_taken=True)),
        exam=Count("pk", filter=Q(history_only=False)), cbct=Count("pk", filter=Q(cbct_done=True)))
    journey = set(patient.treatment_steps.exclude(step_type__journey_step="").values_list(
        "step_type__journey_step", flat=True))
    plans = patient.treatment_plans.exclude(status="cancelled")
    items = plans.values_list("items__step_type__category", "items__status")
    restorative = [status for category, status in items if category == TreatmentStepType.Category.RESTORATIVE]
    implant_planned = any(category == TreatmentStepType.Category.IMPLANT for category, _status in items)
    prostheses = list(patient.prostheses.filter(is_temporary=False).values_list("status", flat=True))
    cbct_doc = patient.documents.filter(kind="xray").exists()
    cbct_asked = patient.outside_requests.filter(kind="cbct").exists()
    fit = clearance(patient)
    done = {
        "medical": bool(exams["medical"]), "dental": bool(exams["dental"]), "exam": bool(exams["exam"]),
        "impression": "impression" in journey,
        "cbct": "cbct" in journey or bool(exams["cbct"]) or cbct_doc,
        "plan": plans.exists(),
        "fitness": fit is not None and fit["state"] in ("fit", "cleared"),
        "surgery": patient.surgeries.exists(),
        "restorative": bool(restorative) and all(status in ("done", "cancelled") for status in restorative),
        "delivery": bool(prostheses) and all(status == Prosthesis.Status.DELIVERED for status in prostheses),
    }
    shown = {code: True for code in CODES}
    shown["fitness"] = fit is not None
    shown["restorative"] = bool(restorative)
    shown["delivery"] = bool(prostheses)
    notes = {}
    if cbct_asked and not done["cbct"]:
        notes["cbct"] = _("asked from a centre")
    if fit is not None and fit["state"] in ("waiting", "not_fit"):
        notes["fitness"] = _("waiting for the answer") if fit["state"] == "waiting" else _("not fit yet")
    if restorative:
        left = sum(1 for status in restorative if status not in ("done", "cancelled"))
        if left:
            notes["restorative"] = _("%(n)s left") % {"n": left}
    optional = set()
    if not done["surgery"] and not implant_planned:
        optional.add("surgery")  # needed only when an implant (or another surgery) is planned
    return done, shown, notes, optional, fit


def file_steps(patient, current=None):
    """The steps of the file, each done or not, with the next one to do marked."""
    done, shown, notes, optional, fit = _state(patient)
    codes = [code for code in CODES if shown[code]]
    last_done = max((codes.index(code) for code in codes if done[code]), default=-1)
    steps, next_found = [], False
    number = 0
    for code, label, icon in STEPS:
        if not shown[code]:
            continue
        number += 1
        position = codes.index(code)
        passed = code in SKIPPABLE and position < last_done  # skipped: a later step is done
        is_next = (not done[code] and not next_found and code not in optional and not passed
                   and (position > last_done or code not in SKIPPABLE))
        next_found = next_found or is_next
        url = step_url(patient, code)
        if code == "fitness" and fit is not None and fit["consult"] is not None:
            url = fit["consult"].get_absolute_url()
        if code == "delivery":
            waiting = patient.prostheses.filter(is_temporary=False).exclude(status="delivered").first()
            if waiting is not None:
                url = reverse("surgery:delivery_check", args=[waiting.pk])
        steps.append({"code": code, "number": number, "label": label, "icon": icon, "done": done[code],
                      "next": is_next, "optional": code in optional, "current": code == current,
                      "skipped": passed and not done[code], "note": notes.get(code, ""), "url": url})
    return steps


def next_step(steps):
    return next((step for step in steps if step["next"]), None)


def after_step(request, patient, code):
    """Where to go once a step is saved: the next step when the dentist is going through the file in order,
    else nowhere special (None)."""
    if not (request.GET.get("flow") or request.POST.get("flow")) or code not in FLOW:
        return None
    position = FLOW.index(code)
    if position + 1 < len(FLOW):
        return step_url(patient, FLOW[position + 1])
    return None
