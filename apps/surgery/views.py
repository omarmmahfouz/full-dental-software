from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.http import require_POST

from apps.charting.models import ToothChange, ToothState
from apps.charting.plans import complete_plan_items
from apps.charting.rules import Change, _snapshot, apply_changes, current_states, plan_changes, state_label
from apps.charting.sync import missing_teeth
from apps.charting.teeth import format_teeth
from apps.clinical.models import ChartEffect, TreatmentStepType
from apps.core.approvals import needs_approval, request_change
from apps.core.mixins import role_required
from apps.core.models import ChangeRequest, branch_for_user
from apps.core.roles import CLINICAL, HEAD_CIA, MANAGEMENT, OWNER, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.patients.medical import clearance
from apps.prescriptions.models import InstructionSheet
from apps.patients.sequence import file_steps
from apps.patients.access import get_clinical_patient_or_403, visible_patients
from apps.scheduling.models import Appointment
from apps.stock.implants import lot_choices, take_implants

from .finder import FinderForm, SiteFacts, export_csv, filter_sites, procedure_totals, prosthesis_totals, statistics
from .forms import DeliveryCheckForm, ImplantUpdateForm, ProsthesisForm, SurgeryForm, SurgerySiteFormSet
from .models import DaySupervisor, DeliveryCheck, ImplantSystem, Prosthesis, SavedSearch, Surgery, SurgerySite
from .followup import follow_up
from .prostheses import apply_stage, plan_from_surgery


# The design of the surgery chart (templates/surgery/_arch_designer.html): what can be added to a tooth, and the
# usual implant sizes offered as buttons (any other size is typed).
ARCH_ADDONS = [(name, label) for name, label in SurgerySite.PROCEDURES
               if name in ("closed_sinus", "open_sinus", "gbr", "expansion", "splitting", "flap")]
IMPLANT_DIAMETERS = ["3.0", "3.3", "3.5", "3.75", "4.0", "4.2", "4.5", "4.8", "5.0", "5.5", "6.0"]
IMPLANT_LENGTHS = ["6", "7", "8", "8.5", "10", "11.5", "12", "13", "14", "16"]


def arch_view(sites, pontics):
    """The design of a saved surgery, drawn like the designer: {"upper": [...], "lower": [...]}, one cell per tooth
    with its role (implant / immediate / extraction), pontic, size, add-ons and its place in a bridge bar."""
    from apps.charting.teeth import LOWER, UPPER

    by_tooth = {site.tooth: site for site in sites}
    addons = dict(ARCH_ADDONS)
    rows = {}
    for jaw, arch in (("upper", UPPER), ("lower", LOWER)):
        cells = []
        for index, tooth in enumerate(arch):
            site = by_tooth.get(tooth)
            role = ""
            if site is not None:
                if site.has_implant:
                    role = "immediate" if site.immediate_implant or site.extraction else "implant"
                elif site.extraction:
                    role = "extraction"
            cells.append({
                "tooth": tooth, "role": role, "pontic": tooth in pontics, "d": 7 - index if index < 8 else index - 8,
                "size": f"{site.diameter_mm}×{site.length_mm}" if site is not None and site.implant_diameter
                and site.implant_length else "",
                "addons": "".join(str(addons[name])[:1] for name in addons if site is not None and getattr(site, name)),
                "bar": "", "midline": index == 8,
            })
        # A bar under the teeth of a bridge or full arch (implants and pontics side by side, with a pontic).
        run = []
        for cell in cells + [None]:
            if cell is not None and (cell["pontic"] or cell["role"] in ("implant", "immediate")):
                run.append(cell)
                continue
            if len(run) > 1 and any(c["pontic"] for c in run):
                for position, member in enumerate(run):
                    member["bar"] = "bar-start" if position == 0 else "bar-end" if position == len(run) - 1 else "bar-mid"
            run = []
        rows[jaw] = cells
    return rows if (by_tooth or pontics) else None


def _surgery_time(surgery):
    """When chart history and plan items should say the surgery happened."""
    if surgery.date == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.combine(surgery.date, time(12)))


def update_chart_for_surgery(surgery, user):
    """Extractions become missing teeth, placed implants become implants on the chart."""
    patient = surgery.patient
    changes = []
    for site in surgery.sites.all():
        if site.has_implant:
            changes += plan_changes(patient, ChartEffect.IMPLANT, [site.tooth], sites={site.tooth: site})
        elif site.extraction:
            changes += plan_changes(patient, ChartEffect.EXTRACTION, [site.tooth])
    changes += pontic_changes(patient, surgery, changes)
    changed = apply_changes(patient, changes, user, ToothChange.Source.SURGERY, surgery=surgery,
                            when=_surgery_time(surgery))
    if changed:
        Surgery.objects.filter(pk=surgery.pk).update(chart_updated=True)
    return changed


def pontic_changes(patient, surgery, changes):
    """The pontics of the design show on the chart as pontics, not missing (an extracted tooth left as a pontic
    too). A tooth that has an implant is left as it is."""
    S = ToothState.Status
    by_tooth = {change.tooth: change for change in changes}
    states = current_states(patient)
    added = []
    for tooth in surgery.pontic_teeth:
        change = by_tooth.get(tooth)
        if change is not None:
            if change.after.get("status") == S.MISSING:  # extracted in this surgery, kept as a pontic
                change.after = dict(change.after, status=S.PONTIC)
                change.summary = f"{state_label(change.before)} → {state_label(change.after)}"
            continue
        before = _snapshot(states.get(tooth))
        if before["status"] in (S.IMPLANT, S.PONTIC):
            continue
        after = dict(before, status=S.PONTIC, implant_site_id=None)
        added.append(Change(tooth=tooth, before=before, after=after,
                            summary=f"{state_label(before)} → {state_label(after)}"))
    return added


def complete_plan_for_surgery(surgery):
    """Tick planned items (implant, extraction, sinus, GBR...) done in this surgery."""
    done = []
    implant_types = TreatmentStepType.objects.filter(chart_effect=ChartEffect.IMPLANT)
    for site in surgery.sites.all():
        types = set(TreatmentStepType.objects.filter(
            surgery_procedure__in=[name for name, _label in SurgerySite.PROCEDURES if getattr(site, name)]
        ))
        if site.has_implant:
            types |= set(implant_types)
        if site.extraction:
            types |= set(TreatmentStepType.objects.filter(chart_effect=ChartEffect.EXTRACTION))
        for step_type in types:
            done += complete_plan_items(surgery.patient, step_type, [site.tooth], surgery=surgery,
                                        when=_surgery_time(surgery))
    return done


def _operator_changes(surgery, form, formset, user):
    """Once saved, the operators of a surgery change only with approval (unless an approver edits):
    the new operators are kept aside for the head of CIA and the old ones stay for now."""
    if surgery is None or not needs_approval(user):
        return []
    original = Surgery.objects.get(pk=surgery.pk)  # the form has already put the new values on the instance
    changes = []
    values = {name: form.cleaned_data.get(name) for name in ("operator_1", "operator_2")
              if form.cleaned_data.get(name) != getattr(original, name)}
    for name in values:
        setattr(form.instance, name, getattr(original, name))
    if values:
        changes.append((original, values))
    for site_form in formset.forms:
        site, data = site_form.instance, getattr(site_form, "cleaned_data", {})
        if not site.pk or not data or data.get("DELETE"):
            continue
        before = SurgerySite.objects.get(pk=site.pk).operator
        if data.get("operator") != before:
            changes.append((SurgerySite.objects.get(pk=site.pk), {"operator": data.get("operator")}))
            site.operator = before
    return changes


def _can_edit_surgery(user, surgery):
    if has_role(user, *MANAGEMENT) or surgery.created_by_id == user.pk:
        return True
    me = Dentist.for_user(user)
    return me is not None and (me in surgery.team() or me == surgery.instructor)


# ------------------------------------------------------------ surgeries
def surgery_list(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    qs = Surgery.objects.filter(patient__branch=branch_for_user(request.user)).select_related(
        "patient", "operator_1", "operator_2", "instructor").prefetch_related("sites")
    if is_only_dentist(request.user):
        me = Dentist.for_user(request.user)
        mine = Q(created_by=request.user)
        if me is not None:
            mine |= Q(operator_1=me) | Q(operator_2=me) | Q(assistant=me)
        qs = qs.filter(mine)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(patient__full_name__icontains=q) | Q(patient__file_number__icontains=q))
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "surgery/surgery_list.html", {"page_obj": page, "q": q})


def surgery_edit(request, pk=None):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    surgery = get_object_or_404(Surgery, pk=pk) if pk else None
    if surgery is not None and not _can_edit_surgery(request.user, surgery):
        raise PermissionDenied
    patient = None
    if surgery is None and request.GET.get("patient", "").isdigit():
        patient = visible_patients(request.user).filter(pk=request.GET["patient"]).first()
    initial = {}
    me = Dentist.for_user(request.user)
    if surgery is None and patient is not None and patient.assigned_dentist_id:
        initial["operator_1"] = patient.assigned_dentist
    if surgery is None and me is not None:
        # CIA dentists assist the candidates in surgery.
        initial["instructor" if me.kind == Dentist.Kind.SUPERVISOR else "assistant"] = me
    if surgery is None and "instructor" not in initial:
        initial["instructor"] = DaySupervisor.on(branch_for_user(request.user), timezone.localdate(),
                                                 timezone.localtime().time())
    form = SurgeryForm(request.POST or None, request.FILES or None, instance=surgery, user=request.user,
                       patient=patient, initial=initial)
    formset = SurgerySiteFormSet(request.POST or None, request.FILES or None,
                                 instance=surgery or Surgery(), prefix="sites",
                                 form_kwargs={"branch": surgery.branch if surgery else branch_for_user(request.user)})
    if request.method == "POST" and form.is_valid():
        formset.team = tuple(d for d in (form.cleaned_data.get("operator_1"), form.cleaned_data.get("operator_2")) if d)
    details_ok = True
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        procedures = {name for row in formset.cleaned_data if row and not row.get("DELETE")
                      for name, _label in SurgerySite.PROCEDURES if row.get(name)}
        details_ok = form.require_details(procedures)
    if request.method == "POST" and details_ok and form.is_valid() and formset.is_valid():
        operator_requests = _operator_changes(surgery, form, formset, request.user)
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.patient = form.cleaned_data["patient_lookup"]
            visit_pk = request.GET.get("appointment", "")
            if not obj.appointment_id and visit_pk.isdigit():  # started from the visit page
                obj.appointment = Appointment.objects.filter(pk=visit_pk, patient=obj.patient).first()
            if not obj.pk:
                obj.branch = branch_for_user(request.user)
                obj.created_by = request.user
            if obj.instructor_id is None:  # the supervisor of the surgery day, written by the juniors (round 15)
                at = timezone.localtime(obj.appointment.scheduled_at).time() if obj.appointment_id else None
                obj.instructor = DaySupervisor.on(obj.branch, obj.date, at)
            obj.save()
            formset.instance = obj
            formset.save()
            implant_teeth = {site.tooth for site in obj.sites.all() if site.has_implant}
            if implant_teeth & set(obj.pontic_teeth):  # a tooth with an implant is not a pontic
                obj.pontics = format_teeth(set(obj.pontic_teeth) - implant_teeth)
                obj.save(update_fields=["pontics"])
            take_implants(obj, request.user)
            changed = update_chart_for_surgery(obj, request.user) if form.cleaned_data.get("update_chart") else 0
            done = complete_plan_for_surgery(obj)
            planned = plan_from_surgery(obj, request.user)
        message = _("Surgery %(number)s saved.") % {"number": obj.number}
        if changed:
            message += " " + _("Dental chart updated for %(n)s teeth.") % {"n": changed}
        if done:
            message += " " + _("%(n)s treatment plan items marked as done.") % {"n": len(done)}
        if planned:
            message += " " + _("Planned on the implants: %(what)s.") % {"what": "; ".join(p.label for p in planned)}
        messages.success(request, message)
        for target, values in operator_requests:
            request_change(ChangeRequest.Kind.OPERATOR, target, values, request.user,
                           _("Operator changed after the surgery chart was saved."))
        if operator_requests:
            messages.warning(request, _("Changing the operator after saving needs approval: it was sent to the head "
                                        "of CIA. The rest is saved."))
        if request.GET.get("flow") and surgery is None:  # the visit flow: surgery -> suggested prescription
            return redirect(f"{reverse('prescriptions:create', args=[obj.patient_id])}?surgery={obj.pk}&flow=1")
        return redirect(obj)
    chart_patient = surgery.patient if surgery else patient
    return render(request, "surgery/surgery_form.html", {
        "form": form, "formset": formset, "surgery": surgery,
        "title": _("Edit surgery chart") if surgery else _("New surgery chart"),
        "procedures": SurgerySite.PROCEDURES, "addons": ARCH_ADDONS,
        "implant_systems": ImplantSystem.objects.filter(is_active=True),
        "diameters": IMPLANT_DIAMETERS, "lengths": IMPLANT_LENGTHS,
        "missing": format_teeth(missing_teeth(chart_patient)) if chart_patient else "",
        "file_steps": file_steps(patient, current="surgery") if patient is not None else None,
        "clearance": clearance(patient) if patient is not None else None, "patient": chart_patient,
    })


def implant_lots(request):
    """Implants in stock for the chosen company (and size), for the surgery chart."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    system = request.GET.get("system", "")
    rows = lot_choices(system=system, branch=branch_for_user(request.user)) if system.isdigit() else []
    return JsonResponse({"lots": [{k: str(v) for k, v in row.items()} for row in rows]})


def surgery_detail(request, pk):
    surgery = get_object_or_404(
        Surgery.objects.select_related("patient", "instructor", "operator_1", "operator_2", "assistant"), pk=pk
    )
    get_clinical_patient_or_403(request.user, surgery.patient_id)
    sites = list(surgery.sites.select_related("implant_system"))
    return render(request, "surgery/surgery_detail.html", {
        "surgery": surgery, "sites": sites, "procedures": SurgerySite.PROCEDURES,
        "arch": arch_view(sites, surgery.pontic_teeth), "follow_up": follow_up(surgery),
        "photos": surgery.photos.select_related("photo_type"),
        "can_edit": _can_edit_surgery(request.user, surgery),
        "print": request.GET.get("print") == "1",
    })


@require_POST
def follow_up_ask(request, pk):
    """The dentist asks the reception to book the visit after the surgery (see followup.py)."""
    from .followup import ask_reception

    surgery = get_object_or_404(Surgery.objects.select_related("patient"), pk=pk)
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    get_clinical_patient_or_403(request.user, surgery.patient_id)
    patient_request, created = ask_reception(surgery, request.user)
    if created:
        messages.success(request, _("The reception will call %(name)s to book the visit (%(date)s).") % {
            "name": surgery.patient.full_name, "date": patient_request.wanted_from.strftime("%d/%m/%Y")})
    else:
        messages.info(request, _("This visit is already on the reception's list."))
    return redirect(request.POST.get("next") or surgery.get_absolute_url())


# ------------------------------------------------------------ implants
def implant_detail(request, pk):
    site = get_object_or_404(SurgerySite.objects.select_related("surgery__patient", "implant_system"), pk=pk)
    patient = get_clinical_patient_or_403(request.user, site.surgery.patient_id)
    can_edit = has_role(request.user, *CLINICAL)
    form = ImplantUpdateForm(request.POST or None, instance=site) if can_edit else None
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        was_failed = site.implant_status == SurgerySite.ImplantStatus.FAILED
        if form.is_valid():
            with transaction.atomic():
                site = form.save()
                if site.implant_status == SurgerySite.ImplantStatus.FAILED and not was_failed:
                    changes = [c for c in plan_changes(patient, ChartEffect.IMPLANT_FAILED, [site.tooth])]
                    apply_changes(patient, changes, request.user, ToothChange.Source.MANUAL)
            messages.success(request, _("Implant updated."))
            return redirect("surgery:implant", pk=site.pk)
    return render(request, "surgery/implant_detail.html", {
        "site": site, "patient": patient, "form": form,
        "checks": site.follow_ups.select_related("dentist"),
        "complications": site.complications.select_related("dentist"),
        "months": round((timezone.localdate() - site.surgery.date).days / 30.44, 1)})


# ------------------------------------------------------------ prostheses on implants
def prosthesis_edit(request, patient_pk=None, pk=None):
    """A single crown, a bridge or a full arch: on which implants, how many units, which teeth are pontics."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    prosthesis = get_object_or_404(Prosthesis, pk=pk) if pk else None
    patient = get_clinical_patient_or_403(request.user, prosthesis.patient_id if prosthesis else patient_pk)
    initial = {}
    me = Dentist.for_user(request.user)
    if prosthesis is None:
        initial["dentist"] = me
        if request.GET.get("implant", "").isdigit():
            initial["implants"] = [int(request.GET["implant"])]
    form = ProsthesisForm(request.POST or None, instance=prosthesis, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.patient = patient
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
            changed = apply_stage(obj, request.user)
        message = _("Saved: %(what)s.") % {"what": obj.label}
        if changed:
            message += " " + _("Implants and chart updated (%(n)s).") % {"n": changed}
        messages.success(request, message)
        return redirect("charting:chart", patient_pk=patient.pk)
    return render(request, "surgery/prosthesis_form.html", {
        "form": form, "patient": patient, "prosthesis": prosthesis,
        "title": _("Edit prosthesis") if prosthesis else _("New prosthesis on implants"),
    })


@require_POST
def prosthesis_delete(request, pk):
    prosthesis = get_object_or_404(Prosthesis, pk=pk)
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient = get_clinical_patient_or_403(request.user, prosthesis.patient_id)
    prosthesis.delete()
    messages.success(request, _("Prosthesis deleted. The implant stages stay as they are."))
    return redirect("charting:chart", patient_pk=patient.pk)


def delivery_check(request, pk):
    """The delivery checklist of a prosthesis on implants: tap each point, write the torque, then "delivered"
    (the implants become loaded and the pontics show on the chart)."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    prosthesis = get_object_or_404(Prosthesis.objects.prefetch_related("implants__implant_system"), pk=pk)
    patient = get_clinical_patient_or_403(request.user, prosthesis.patient_id)
    check = getattr(prosthesis, "delivery_check", None)
    if check is None:
        check = DeliveryCheck(prosthesis=prosthesis, dentist=prosthesis.dentist or Dentist.for_user(request.user),
                              follow_up_on=timezone.localdate() + timedelta(days=7))
        if prosthesis.lab_request_id and prosthesis.lab_request.shade:
            check.shade = prosthesis.lab_request.shade
    groups = DeliveryCheck.items_for(prosthesis)
    form = DeliveryCheckForm(request.POST or None, instance=check)
    if request.method == "POST" and form.is_valid():
        allowed = {code for _group, rows in groups for code, _label, _optional in rows}
        check = form.save(commit=False)
        check.ticked = [code for code in request.POST.getlist("tick") if code in allowed]
        if check.pk is None:
            check.created_by = request.user
        deliver = request.POST.get("action") == "deliver"
        with transaction.atomic():
            check.save()
            changed = 0
            if deliver:
                prosthesis.status, prosthesis.delivered_on = Prosthesis.Status.DELIVERED, check.date
                prosthesis.dentist = prosthesis.dentist or check.dentist
                prosthesis.save(update_fields=["status", "delivered_on", "dentist", "updated_at"])
                changed = apply_stage(prosthesis, request.user)
        if deliver:
            message = _("Delivered: %(what)s.") % {"what": prosthesis.label}
            if changed:
                message += " " + _("Implants and chart updated (%(n)s).") % {"n": changed}
            messages.success(request, message)
            missing = len(check.missing())
            if missing:
                messages.warning(request, ngettext(
                    "%(n)s point of the checklist is not ticked (in red).",
                    "%(n)s points of the checklist are not ticked (in red).", missing) % {"n": missing})
        else:
            messages.success(request, _("Checklist saved."))
        return redirect("surgery:delivery_check", pk=prosthesis.pk)
    done = set(check.ticked)
    return render(request, "surgery/delivery_check.html", {
        "patient": patient, "prosthesis": prosthesis, "check": check, "form": form, "done": done,
        "groups": [(group, [(code, label, optional, code in done) for code, label, optional in rows])
                   for group, rows in groups],
        "progress": check.progress(), "sheet": InstructionSheet.objects.filter(
            is_active=True, procedures__contains="delivery").first(),
    })


# ------------------------------------------------------------ case finder
QUICK_SEARCHES = [
    (gettext_lazy("Healing - waiting 2nd stage"), {"status": "placed"}),
    (gettext_lazy("Uncovered - waiting impression / scan"), {"status": "uncovered"}),
    (gettext_lazy("Impression taken - waiting delivery"), {"status": "impression"}),
    (gettext_lazy("Loaded implants"), {"status": "loaded"}),
    (gettext_lazy("Failed implants"), {"status": "failed"}),
    (gettext_lazy("Sinus lift cases"), {"procedures_any": ["open_sinus", "closed_sinus"], "result": "sites"}),
    (gettext_lazy("GBR / block graft cases"), {"procedures_any": "gbr", "result": "sites"}),
    (gettext_lazy("Immediate implants"), {"procedures_any": "immediate_implant"}),
    (gettext_lazy("Full-arch cases"), {"full_arch": "yes"}),
    (gettext_lazy("Guided implants"), {"procedures_any": "guided"}),
    (gettext_lazy("Single crowns"), {"prosthesis": "single"}),
    (gettext_lazy("Bridges"), {"prosthesis": "bridge"}),
    (gettext_lazy("Splitting cases"), {"procedures_any": "splitting", "result": "sites"}),
    (gettext_lazy("Expansion cases"), {"procedures_any": "expansion", "result": "sites"}),
]
# One tap groups the results found (the filters stay), with the survival and the loading of each group.
QUICK_GROUPS = [
    (gettext_lazy("Full arch or not"), "full_arch"), (gettext_lazy("Guided or freehand"), "guided"),
    (gettext_lazy("Crown, bridge or full arch"), "prosthesis"), (gettext_lazy("Splitting"), "splitting"),
    (gettext_lazy("Expansion"), "expansion"), (gettext_lazy("Sinus lift"), "sinus"),
    (gettext_lazy("Immediate or delayed"), "immediate"), (gettext_lazy("GBR"), "graft"),
    (gettext_lazy("Implant company"), "company"), (gettext_lazy("Operator"), "operator"),
]


@role_required(*MANAGEMENT)
def finder(request):
    form = FinderForm(request.GET or None)
    data = form.cleaned_data if form.is_bound and form.is_valid() else {}
    sites = filter_sites(data)
    facts = SiteFacts(sites, data.get("full_arch", ""))
    if request.GET.get("export") == "csv":
        return export_csv(facts, filename="cia-cases.csv")
    overall, groups = statistics(facts, data.get("group_by", ""), data.get("group_by_2", ""))
    params = request.GET.copy()
    for key in ("page", "export"):
        params.pop(key, None)
    page = Paginator(facts.sites, 50).get_page(request.GET.get("page"))
    saved = SavedSearch.objects.filter(Q(owner=request.user) | Q(shared=True))
    quick = [(label, urlencode(query, doseq=True)) for label, query in QUICK_SEARCHES]
    quick_groups = []
    for label, code in QUICK_GROUPS:
        query = params.copy()
        query["group_by"] = code
        query.pop("group_by_2", None)
        quick_groups.append({"label": label, "query": query.urlencode(), "active": data.get("group_by") == code})
    reasons = {}
    with translation.override("ar"):  # the reasons and the title are read by the reception
        for site in facts.sites:
            text = f"{site.tooth} {site.get_implant_status_display() or '، '.join(site.procedure_labels())}"
            reasons.setdefault(site.surgery.patient, []).append(text)
        status_labels = [str(label) for code, label in SurgerySite.ImplantStatus.choices
                         if code in (data.get("status") or [])]
        call_title = (_("Implant cases: %(what)s") % {"what": "، ".join(status_labels)}
                      if status_labels else str(_("Implant cases")))
    call_rows = [(patient, "; ".join(texts)) for patient, texts in reasons.items()]
    chosen = set(data.get("procedures_any") or [])
    totals = procedure_totals(facts.sites)
    for row in totals:  # one click filters by that procedure, a second click removes it
        query = params.copy()
        query.setlist("procedures_any", sorted(chosen ^ {row["code"]}))
        if row["code"] not in SurgerySite.IMPLANT_PROCEDURES:
            query["result"] = "sites"  # e.g. extractions or sinus lifts without an implant count too
        row["active"] = row["code"] in chosen
        row["query"] = query.urlencode()
    status_chips = []
    chosen_status = set(data.get("status") or [])
    for code, label in SurgerySite.ImplantStatus.choices:
        query = params.copy()
        query.setlist("status", sorted(chosen_status ^ {code}))
        status_chips.append({"label": label, "active": code in chosen_status, "query": query.urlencode()})
    return render(request, "surgery/finder.html", {
        "procedure_totals": totals, "status_chips": status_chips, "prosthesis_totals": prosthesis_totals(facts.sites),
        "call_rows": call_rows,
        "call_title": call_title,
        "form": form, "page_obj": page, "overall": overall, "groups": groups, "query": params.urlencode(),
        "saved": saved, "quick": quick, "quick_groups": quick_groups, "group_label": dict(form.fields["group_by"].choices).get(data.get("group_by")),
        "group_label_2": dict(form.fields["group_by_2"].choices).get(data.get("group_by_2")),
    })


@role_required(*MANAGEMENT)
@require_POST
def finder_save(request):
    name = request.POST.get("name", "").strip()
    query = request.POST.get("query", "")
    if name:
        SavedSearch.objects.create(name=name[:120], query=query, owner=request.user,
                                   shared=request.POST.get("shared") == "on")
        messages.success(request, _("Search saved."))
    return redirect(f"{reverse('surgery:finder')}?{query}")


@role_required(*MANAGEMENT)
@require_POST
def finder_delete(request, pk):
    search = get_object_or_404(SavedSearch, pk=pk)
    if search.owner_id != request.user.pk and not has_role(request.user, OWNER, HEAD_CIA):
        raise PermissionDenied
    search.delete()
    messages.success(request, _("Saved search deleted."))
    return redirect("surgery:finder")
