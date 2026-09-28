"""The order a dentist fills a new patient's file in: medical history, dental history, dental examination,
treatment plan, then the surgery chart. The patient's page shows the five steps with the next one to do; a step
opened from there ("flow") goes on to the next one when it is saved."""

from django.db.models import Count, Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

STEPS = [
    ("medical", _("Medical history"), "bi-heart-pulse"),
    ("dental", _("Dental history"), "bi-chat-square-text"),
    ("exam", _("Dental examination"), "bi-clipboard2-pulse"),
    ("plan", _("Treatment plan"), "bi-list-check"),
    ("surgery", _("Surgery chart"), "bi-implant"),
]
CODES = [code for code, _label, _icon in STEPS]


def step_url(patient, code, flow=True):
    url = {
        "medical": reverse("patients:medical_history", args=[patient.pk]) + "?part=medical",
        "dental": reverse("patients:medical_history", args=[patient.pk]) + "?part=dental",
        "exam": reverse("charting:exam_create", args=[patient.pk]),
        "plan": reverse("charting:plan_create", args=[patient.pk]),
        "surgery": reverse("surgery:create") + f"?patient={patient.pk}",
    }[code]
    if flow and code != "surgery":  # the surgery chart is filled on the day of the surgery, on its own
        url += ("&" if "?" in url else "?") + "flow=1"
    return url


def file_steps(patient, current=None):
    """The five steps, each done or not, with the first one not done marked as the next."""
    exams = patient.examinations.aggregate(
        medical=Count("pk", filter=Q(medical_taken=True)), dental=Count("pk", filter=Q(dental_taken=True)),
        exam=Count("pk", filter=Q(history_only=False)))
    done = {
        "medical": bool(exams["medical"]),
        "dental": bool(exams["dental"]),
        "exam": bool(exams["exam"]),
        "plan": patient.treatment_plans.exclude(status="cancelled").exists(),
        "surgery": patient.surgeries.exists(),
    }
    # The surgery chart is needed only when an implant (or another surgery) is planned.
    optional = {"surgery"} if not done["surgery"] and not patient.treatment_plans.exclude(status="cancelled").filter(
        items__step_type__category="implant").exists() else set()
    steps, next_found = [], False
    for number, (code, label, icon) in enumerate(STEPS, start=1):
        is_next = not done[code] and not next_found and code not in optional
        next_found = next_found or is_next
        steps.append({"code": code, "number": number, "label": label, "icon": icon, "done": done[code],
                      "next": is_next, "optional": code in optional, "current": code == current,
                      "url": step_url(patient, code)})
    return steps


def after_step(request, patient, code):
    """Where to go once a step is saved: the next step when the dentist is going through the file in order,
    else nowhere special (None)."""
    if not (request.GET.get("flow") or request.POST.get("flow")):
        return None
    position = CODES.index(code)
    if position + 1 < len(CODES) - 1:  # up to the treatment plan
        return step_url(patient, CODES[position + 1])
    return None
