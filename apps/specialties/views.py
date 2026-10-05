"""The specialists' pages: referrals (the letter, booking, the answer back) and each specialist's chart."""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, FRONT_DESK, MANAGEMENT, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403, get_visible_patient_or_403, other_place_page
from apps.patients.models import Patient

from . import shades
from .forms import (
    CanalFormSet, EndoCaseForm, EndoVisitForm, OrthoCaseForm, OrthoVisitForm, ProsthoCaseForm, ReferralForm,
    ReplyForm, ShadeRecordForm, TMJExamForm, TMJVisitForm,
)
from .models import EndoCanal, EndoCase, OrthoCase, OrthoVisit, ProsthoCase, Referral, ShadeRecord, TMJExam
from .services import finish_endo, tell_about_referral, tell_reply

# Canals usually found in each tooth (FDI), offered with one click on the endodontic chart.
USUAL_CANALS = {
    "upper_molar": ["MB", "MB2", "DB", "P"], "lower_molar": ["MB", "ML", "D"],
    "upper_premolar": ["B", "P"], "lower_premolar": ["Single"], "anterior": ["Single"],
}


def usual_canals(tooth):
    upper, position = tooth // 10 in (1, 2), tooth % 10
    if position >= 6:
        return USUAL_CANALS["upper_molar" if upper else "lower_molar"]
    if position >= 4:
        return USUAL_CANALS["upper_premolar" if upper else "lower_premolar"]
    return USUAL_CANALS["anterior"]


def _patient_from_request(request):
    pk = request.GET.get("patient") or request.POST.get("patient") or ""
    if not pk.isdigit():
        raise Http404
    return get_clinical_patient_or_403(request.user, int(pk))


def _record(request, model, pk):
    """A specialist record of a patient of the place worked in now (else the page offers to switch place)."""
    record = get_object_or_404(model.objects.select_related("patient", "dentist", "branch"), pk=pk)
    switch = other_place_page(request, record.patient.branch_id)
    if switch is not None:
        return record, switch
    get_clinical_patient_or_403(request.user, record.patient_id)
    return record, None


def _me(request):
    return Dentist.for_user(request.user)


def _place(request):
    return branch_for_user(request.user)


def _referral_from(request, patient):
    pk = request.GET.get("referral") or request.POST.get("referral") or ""
    return Referral.objects.filter(pk=pk, patient=patient).first() if pk.isdigit() else None


# ------------------------------------------------------------------ the list of cases
def cases(request):
    """Every specialist record at the place: endodontic cases, TMJ examinations, orthodontic cases, shades."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    place = _place(request)
    kind = request.GET.get("kind") if request.GET.get("kind") in ("endo", "tmj", "ortho", "prostho", "shade") \
        else "endo"
    me = _me(request)
    mine = request.GET.get("mine") == "1" or (is_only_dentist(request.user) and me is not None
                                              and request.GET.get("mine") != "0")
    models = {"endo": EndoCase, "tmj": TMJExam, "ortho": OrthoCase, "prostho": ProsthoCase, "shade": ShadeRecord}
    counts = {}
    for code, model in models.items():
        rows = model.objects.filter(branch=place)
        if mine and me is not None:
            rows = rows.filter(dentist=me)
        counts[code] = rows.count()
    rows = models[kind].objects.filter(branch=place).select_related("patient", "dentist")
    if mine and me is not None:
        rows = rows.filter(dentist=me)
    status = request.GET.get("status", "")
    if status and kind in ("endo", "ortho", "prostho"):
        rows = rows.filter(status=status)
    page = Paginator(rows, 100).get_page(request.GET.get("page"))
    return render(request, "specialties/cases.html", {
        "kind": kind, "counts": counts, "page_obj": page, "mine": mine, "me": me, "status": status,
        "statuses": {"endo": EndoCase.Status.choices, "ortho": OrthoCase.Status.choices,
                     "prostho": ProsthoCase.Status.choices}.get(kind, []),
        "open_referrals": Referral.objects.filter(branch=place, status__in=Referral.OPEN).filter(
            Q(to_dentist=me) if mine and me is not None else Q()).count(),
    })


def patient_records(request, pk):
    """A patient's specialists: the referrals, and (for the doctors) the endodontic, TMJ, orthodontic and shade
    records, with a button for each new one."""
    from .services import records_of

    switch = other_place_page(request, Patient.objects.filter(pk=pk).values_list("branch", flat=True).first())
    if switch is not None:
        return switch
    if not has_role(request.user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied
    patient = get_visible_patient_or_403(request.user, pk)
    clinical = has_role(request.user, *CLINICAL)
    records = records_of(patient)
    if not clinical:
        records = {"referrals": records["referrals"]}
    specialists = Dentist.objects.active().working_at(patient.branch).exclude(specialty__in=("", "general")) \
        .order_by("specialty", "full_name")
    return render(request, "specialties/patient.html", {
        "patient": patient, "records": records, "clinical": clinical, "specialists": specialists,
        "is_desk": has_role(request.user, *FRONT_DESK),
    })


# ------------------------------------------------------------------ referrals
def referral_list(request):
    if not has_role(request.user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied
    place = _place(request)
    me = _me(request)
    show = request.GET.get("show") or ("to_me" if is_only_dentist(request.user) else "open")
    rows = Referral.objects.filter(branch=place).select_related("patient", "from_dentist", "to_dentist", "appointment")
    if show == "to_me":
        rows = rows.filter(to_dentist=me) if me is not None else rows.none()
    elif show == "from_me":
        rows = rows.filter(from_dentist=me) if me is not None else rows.none()
    elif show == "to_book":
        rows = rows.filter(status=Referral.Status.SENT).exclude(to_dentist=None)
    elif show == "open":
        rows = rows.filter(status__in=Referral.OPEN)
    page = Paginator(rows, 100).get_page(request.GET.get("page"))
    return render(request, "specialties/referral_list.html", {
        "page_obj": page, "show": show, "me": me, "is_desk": has_role(request.user, *FRONT_DESK),
        "to_book": Referral.objects.filter(branch=place, status=Referral.Status.SENT).exclude(to_dentist=None).count(),
    })


def referral_create(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient = _patient_from_request(request)
    place = _place(request)
    initial = {"from_dentist": _me(request), "teeth": request.GET.get("teeth", "")[:100]}
    if request.GET.get("to", "").isdigit():
        initial["to_dentist"] = int(request.GET["to"])
    form = ReferralForm(request.POST or None, place=place, initial=initial)
    if request.method == "POST" and form.is_valid():
        referral = form.save(commit=False)
        referral.patient, referral.branch, referral.created_by = patient, place, request.user
        referral.save()
        tell_about_referral(referral, request.user)
        messages.success(request, _("Referral %(number)s sent to %(doctor)s. The reception is told to book the "
                                    "patient.") % {"number": referral.number, "doctor": referral.to_name}
                         if referral.to_dentist_id else
                         _("Referral %(number)s written: print it for the patient.") % {"number": referral.number})
        return redirect(referral)
    return render(request, "specialties/referral_form.html", {"form": form, "patient": patient})


def referral_detail(request, pk):
    referral = get_object_or_404(Referral.objects.select_related("patient", "from_dentist", "to_dentist", "branch",
                                                                 "appointment", "replied_by"), pk=pk)
    switch = other_place_page(request, referral.patient.branch_id)
    if switch is not None:
        return switch
    if not has_role(request.user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied
    get_visible_patient_or_403(request.user, referral.patient_id)
    me = _me(request)
    can_reply = has_role(request.user, *CLINICAL) and (
        (me is not None and me.pk == referral.to_dentist_id) or has_role(request.user, *MANAGEMENT))
    form = ReplyForm(request.POST or None, initial={"reply": referral.reply})
    if request.method == "POST":
        if not can_reply:
            raise PermissionDenied
        if form.is_valid():
            referral.reply = form.cleaned_data["reply"]
            referral.replied_at, referral.replied_by = timezone.now(), request.user
            referral.status = Referral.Status.DONE
            referral.save()
            tell_reply(referral, request.user)
            messages.success(request, _("Answer saved and sent to %(doctor)s.") % {"doctor": referral.from_dentist})
            return redirect(referral)
    from apps.charting.models import Examination

    exam = Examination.objects.filter(patient=referral.patient).first()
    return render(request, "specialties/referral_detail.html", {
        "referral": referral, "form": form, "can_reply": can_reply, "exam": exam,
        "conditions": referral.patient.medical_conditions.filter(is_alert=True),
        "is_desk": has_role(request.user, *FRONT_DESK),
        "book_url": f"{reverse('scheduling:appointment_create')}?" + urlencode({
            "patient": referral.patient_id, "dentist": referral.to_dentist_id, "referral": referral.pk,
            "purpose": f"{referral.get_specialty_display()} {referral.teeth}".strip()}) if referral.to_dentist_id else "",
    })


@require_POST
def referral_status(request, pk):
    """The patient did not want it, or the referral is cancelled (by the doctors or the reception)."""
    referral = get_object_or_404(Referral, pk=pk, status__in=Referral.OPEN)
    if not has_role(request.user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied
    get_visible_patient_or_403(request.user, referral.patient_id)
    status = request.POST.get("status")
    if status in (Referral.Status.DECLINED, Referral.Status.CANCELLED):
        referral.status = status
        referral.save(update_fields=["status", "updated_at"])
        messages.info(request, referral.get_status_display())
    return redirect(referral)


# ------------------------------------------------------------------ the charts, one helper for all
def _edit(request, model, form_class, template, pk=None, title="", extra=None, formset_class=None, context=None):
    """New or edit a specialist chart. Returns the page, or goes to the saved record."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    if pk:
        record, switch = _record(request, model, pk)
        if switch is not None:
            return switch
        patient, place = record.patient, record.branch
    else:
        record, patient, place = None, _patient_from_request(request), _place(request)
    initial = dict(extra or {})
    if record is None:
        initial.setdefault("dentist", _me(request))
    form = form_class(request.POST or None, request.FILES or None, instance=record, place=place, initial=initial)
    formset = formset_class(request.POST or None, instance=record or model(), prefix="canals") \
        if formset_class else None
    if request.method == "POST" and form.is_valid() and (formset is None or formset.is_valid()):
        with transaction.atomic():
            saved = form.save(commit=False)
            if record is None:
                saved.patient, saved.branch, saved.created_by = patient, place, request.user
                saved.referral = _referral_from(request, patient)
            saved.save()
            form.save_m2m()
            if formset is not None:
                formset.instance = saved
                formset.save()
        messages.success(request, _("Saved."))
        return redirect(saved)
    return render(request, template, {"form": form, "formset": formset, "patient": patient, "record": record,
                                      "title": title, "referral": _referral_from(request, patient), **(context or {})})


# ------------------------------------------------------------------ endodontics
def endo_edit(request, pk=None):
    extra = {}
    if pk is None and request.GET.get("tooth", "").isdigit():
        extra["tooth"] = int(request.GET["tooth"])
    return _edit(request, EndoCase, EndoCaseForm, "specialties/endo_form.html", pk, _("Endodontic chart"), extra,
                 CanalFormSet, {"canal_names": EndoCanal.NAMES, "usual_canals": USUAL_CANALS})


def endo_detail(request, pk):
    case, switch = _record(request, EndoCase, pk)
    if switch is not None:
        return switch
    visit_form = EndoVisitForm(request.POST or None, prefix="v")
    if request.method == "POST":
        if request.POST.get("action") == "finish":
            step = finish_endo(case, request.user)
            messages.success(request, _("Tooth %(tooth)s obturated: the dental chart shows the root canal.")
                             % {"tooth": case.tooth} if step else _("The case is finished."))
            return redirect(case)
        if request.POST.get("action") == "reopen":
            case.status = EndoCase.Status.OPEN
            case.save(update_fields=["status", "updated_at"])
            return redirect(case)
        if visit_form.is_valid():
            visit = visit_form.save(commit=False)
            visit.case, visit.created_by = case, request.user
            visit.save()
            messages.success(request, _("Visit saved."))
            return redirect(case)
    visits = list(case.visits.all())
    return render(request, "specialties/endo_detail.html", {
        "case": case, "patient": case.patient, "canals": case.canals.all(), "visits": visits,
        "visit_form": visit_form, "medicated": next((v for v in reversed(visits) if v.medication
                                                     and v.medication != "none"), None),
    })


# ------------------------------------------------------------------ TMJ
def tmj_edit(request, pk=None):
    return _edit(request, TMJExam, TMJExamForm, "specialties/record_form.html", pk, _("TMJ examination"))


def tmj_detail(request, pk):
    exam, switch = _record(request, TMJExam, pk)
    if switch is not None:
        return switch
    last = exam.visits.exclude(opening=None).order_by("-date", "-pk").first()
    visit_form = TMJVisitForm(request.POST or None, prefix="v", initial={"opening": last.opening if last else exam.opening})
    if request.method == "POST" and visit_form.is_valid():
        visit = visit_form.save(commit=False)
        visit.exam, visit.created_by = exam, request.user
        visit.save()
        messages.success(request, _("Follow-up saved."))
        return redirect(exam)
    visits = list(exam.visits.all())
    return render(request, "specialties/tmj_detail.html", {
        "exam": exam, "patient": exam.patient, "visits": visits, "visit_form": visit_form,
        "progress": [{"date": exam.exam_date, "opening": exam.opening, "pain": exam.pain_vas}]
        + [{"date": v.date, "opening": v.opening, "pain": v.pain_vas} for v in visits],
    })


# ------------------------------------------------------------------ orthodontics
def ortho_edit(request, pk=None):
    return _edit(request, OrthoCase, OrthoCaseForm, "specialties/record_form.html", pk, _("Orthodontic case"))


def ortho_detail(request, pk):
    case, switch = _record(request, OrthoCase, pk)
    if switch is not None:
        return switch
    last = case.visits.order_by("-date", "-pk").first()
    initial = {"upper_wire": last.upper_wire, "lower_wire": last.lower_wire, "elastics": last.elastics,
               "aligner": (last.aligner + 1) if last and last.aligner else None,
               "next_weeks": last.next_weeks} if last else {"next_weeks": 4}
    visit_form = OrthoVisitForm(request.POST or None, prefix="v", initial=initial)
    if request.method == "POST" and visit_form.is_valid():
        visit = visit_form.save(commit=False)
        visit.case, visit.created_by = case, request.user
        visit.save()
        if case.status == OrthoCase.Status.RECORDS:
            case.status = OrthoCase.Status.ACTIVE
            case.bonded_on = case.bonded_on or visit.date
            case.save(update_fields=["status", "bonded_on", "updated_at"])
        messages.success(request, _("Visit saved."))
        return redirect(case)
    return render(request, "specialties/ortho_detail.html", {
        "case": case, "patient": case.patient, "visits": case.visits.all(), "visit_form": visit_form,
        "wires": OrthoVisit.WIRES, "last": last,
    })


# ------------------------------------------------------------------ prosthodontics (round 15)
def prostho_edit(request, pk=None):
    return _edit(request, ProsthoCase, ProsthoCaseForm, "specialties/record_form.html", pk,
                 _("Prosthodontic chart"))


def prostho_detail(request, pk):
    """The prosthodontic case, with its shades, its lab requests and the prosthetic steps of the treatment log."""
    from apps.clinical.models import StepGroup

    case, switch = _record(request, ProsthoCase, pk)
    if switch is not None:
        return switch
    patient = case.patient
    steps = patient.treatment_steps.filter(step_type__group__in=(
        StepGroup.FIXED, StepGroup.REMOVABLE, StepGroup.IMPLANT_TEETH)).select_related("step_type", "operator")
    return render(request, "specialties/prostho_detail.html", {
        "case": case, "patient": patient, "steps": steps[:40],
        "shades": ShadeRecord.objects.filter(patient=patient).select_related("dentist")[:10],
        "lab_requests": patient.lab_requests.select_related("work_type", "lab")[:10],
    })


# ------------------------------------------------------------------ the shade
def shade_edit(request, pk=None):
    extra = {"teeth": request.GET.get("teeth", "")[:100]} if pk is None else {}
    return _edit(request, ShadeRecord, ShadeRecordForm, "specialties/record_form.html", pk,
                 _("Shade for the prosthesis"), extra)


def shade_detail(request, pk):
    record, switch = _record(request, ShadeRecord, pk)
    if switch is not None:
        return switch
    thirds = [(label, value, shades.COLOURS.get(value, "")) for label, value in (
        (_("Cervical"), record.shade_cervical or record.shade), (_("Middle"), record.shade),
        (_("Incisal"), record.shade_incisal or record.shade))]
    return render(request, "specialties/shade_detail.html", {
        "record": record, "patient": record.patient, "thirds": thirds,
        "stump_colour": shades.COLOURS.get(record.stump, ""),
        "lab_url": f"{reverse('clinical:lab_create')}?patient={record.patient_id}&shade_record={record.pk}",
    })

