"""The treatment page asks for the teeth first (round 15): each tooth then shows how it is now (the chart), what
was done on it before, what is planned for it, and for an implant its stage, its last check and its open
complications. The kinds of work that fit those teeth are offered first."""

from django.http import JsonResponse
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.charting.models import PlanItem, ToothState
from apps.charting.rules import _snapshot, current_states, state_label
from apps.charting.teeth import parse_teeth
from apps.core.roles import CLINICAL, has_role
from apps.patients.access import get_clinical_patient_or_403
from apps.patients.forms import find_patient

from .models import StepGroup

OPEN = ("open", "improving")


def _teeth_of(text):
    try:
        return set(parse_teeth(text or ""))
    except Exception:  # noqa: BLE001 - an old value that does not read is left out
        return set()


def teeth_status(patient, teeth):
    """[{"tooth", "now", "implant", "done", "planned"}] and the kinds of work that fit, first."""
    from apps.surgery.models import ImplantComplication, SurgerySite

    states = current_states(patient)
    steps = list(patient.treatment_steps.select_related("step_type", "operator").order_by("-performed_at")[:300])
    planned = list(PlanItem.objects.filter(plan__patient=patient, status=PlanItem.Status.PLANNED)
                   .select_related("step_type"))
    sites = {}
    for site in SurgerySite.objects.filter(surgery__patient=patient, tooth__in=teeth).select_related(
            "surgery", "implant_system").order_by("surgery__date"):
        if site.has_implant:
            sites[site.tooth] = site  # the latest implant of the tooth
    open_complications = {}
    for row in ImplantComplication.objects.filter(site__in=list(sites.values()), outcome__in=OPEN):
        open_complications.setdefault(row.site_id, []).append(row.get_kind_display())
    groups, rows = [], []

    def offer(*codes):
        for code in codes:
            if code not in groups:
                groups.append(code)

    for tooth in teeth:
        state = states.get(tooth)
        site = state.implant_site if state is not None and state.implant_site_id else sites.get(tooth)
        snap = _snapshot(state)
        done = [{"date": date_format(step.performed_at, "d/m/Y"), "what": str(step.step_type),
                 "by": str(step.operator or ""), "url": step.get_absolute_url()}
                for step in steps if tooth in _teeth_of(step.teeth)][:4]
        plan = [str(item.step_type) for item in planned if tooth in _teeth_of(item.teeth)]
        offer(*[item.step_type.group for item in planned if tooth in _teeth_of(item.teeth)])
        row = {"tooth": tooth, "now": str(state_label(snap, site)), "done": done, "planned": plan, "implant": None}
        status = snap.get("status")
        if site is not None and status in (ToothState.Status.IMPLANT, None, ToothState.Status.PRESENT) \
                and site.implant_status:
            last = site.follow_ups.first()
            row["implant"] = {
                "label": site.implant_label, "stage": site.get_implant_status_display(),
                "placed": date_format(site.surgery.date, "d/m/Y"),
                "loaded": date_format(site.loaded_on, "d/m/Y") if site.loaded_on else "",
                "last_check": (f"{date_format(last.checked_on, 'd/m/Y')}: {last.get_status_display()}"
                               if last else ""),
                "complications": open_complications.get(site.pk, []),
                "url": reverse("surgery:implant", args=[site.pk]),
                "check_url": reverse("surgery:implant_check", args=[site.pk]),
                "complication_url": reverse("surgery:implant_complication", args=[site.pk]),
            }
            if site.implant_status == site.ImplantStatus.LOADED:
                offer(StepGroup.IMPLANT_CARE, StepGroup.IMPLANT_TEETH)
            elif site.implant_status != site.ImplantStatus.FAILED:
                offer(StepGroup.IMPLANT_TEETH, StepGroup.IMPLANT_SURGERY, StepGroup.IMPLANT_CARE)
        elif status in (ToothState.Status.MISSING, ToothState.Status.PONTIC):
            offer(StepGroup.IMPLANT_SURGERY, StepGroup.FIXED, StepGroup.REMOVABLE)
        elif status in (ToothState.Status.ROOT_REMNANT, ToothState.Status.IMPACTED) or snap.get("hopeless"):
            offer(StepGroup.SURGERY, StepGroup.IMPLANT_SURGERY)
        else:
            if snap.get("caries"):
                offer(StepGroup.FILLINGS, StepGroup.ENDO)
            if snap.get("rct") and not snap.get("crown"):
                offer(StepGroup.FIXED)
            if snap.get("crown"):
                offer(StepGroup.FIXED)
        rows.append(row)
    return rows, [str(code) for code in groups]


def teeth_status_json(request):
    if not has_role(request.user, *CLINICAL):
        return JsonResponse({"teeth": [], "groups": []})
    pk = request.GET.get("patient", "")
    patient = None
    if pk.isdigit():
        patient = get_clinical_patient_or_403(request.user, int(pk))
    elif request.GET.get("lookup"):
        found = find_patient(request.GET["lookup"])
        patient = get_clinical_patient_or_403(request.user, found.pk) if found else None
    teeth = sorted(_teeth_of(request.GET.get("teeth")))
    if patient is None or not teeth:
        return JsonResponse({"teeth": [], "groups": []})
    rows, groups = teeth_status(patient, teeth[:16])
    return JsonResponse({"teeth": rows, "groups": groups})


def bill_info_json(request):
    """The usual price of a service for the operator at this place, and what the patient owes now (round 15)."""
    from apps.billing.models import Service, account
    from apps.clinics.prices import price_and_cost
    from apps.core.models import branch_for_user
    from apps.dentists.models import Dentist

    if not has_role(request.user, *CLINICAL):
        return JsonResponse({})
    service = Service.objects.filter(pk=request.GET.get("service") or 0).first()
    dentist = Dentist.objects.filter(pk=request.GET.get("dentist") or 0).first()
    place = branch_for_user(request.user)
    data = {}
    if service is not None:
        price, _cost = price_and_cost(service, dentist, place, request.GET.get("teeth", ""))
        data["price"] = f"{price:.2f}"
    pk = request.GET.get("patient", "")
    patient = None
    if pk.isdigit():
        patient = get_clinical_patient_or_403(request.user, int(pk))
    elif request.GET.get("lookup"):
        patient = find_patient(request.GET["lookup"])
    if patient is not None:
        owes = account(patient)["balance"]
        data["owes"] = f"{owes:.2f}"
        data["owes_text"] = (_("He owes now: %(amount)s") if owes > 0 else _("He owes nothing now.")) % {
            "amount": f"{owes:,.2f}"}
    return JsonResponse(data)

