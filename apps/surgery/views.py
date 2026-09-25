from datetime import datetime, time
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.charting.models import ToothChange
from apps.charting.plans import complete_plan_items
from apps.charting.rules import apply_changes, plan_changes
from apps.clinical.models import ChartEffect, TreatmentStepType
from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, HEAD_CIA, MANAGEMENT, OWNER, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403, visible_patients

from .finder import FinderForm, SiteFacts, export_csv, filter_sites, statistics
from .forms import ImplantUpdateForm, SurgeryForm, SurgerySiteFormSet
from .models import SavedSearch, Surgery, SurgerySite


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
    changed = apply_changes(patient, changes, user, ToothChange.Source.SURGERY, surgery=surgery,
                            when=_surgery_time(surgery))
    if changed:
        Surgery.objects.filter(pk=surgery.pk).update(chart_updated=True)
    return changed


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


def _can_edit_surgery(user, surgery):
    if has_role(user, *MANAGEMENT) or surgery.created_by_id == user.pk:
        return True
    me = Dentist.for_user(user)
    return me is not None and (me in surgery.team() or me == surgery.instructor)


# ------------------------------------------------------------ surgeries
def surgery_list(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    qs = Surgery.objects.select_related("patient", "operator_1", "operator_2", "instructor").prefetch_related("sites")
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
    form = SurgeryForm(request.POST or None, request.FILES or None, instance=surgery, user=request.user,
                       patient=patient, initial=initial)
    formset = SurgerySiteFormSet(request.POST or None, request.FILES or None,
                                 instance=surgery or Surgery(), prefix="sites")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.patient = form.cleaned_data["patient_lookup"]
            if not obj.pk:
                obj.branch = branch_for_user(request.user)
                obj.created_by = request.user
            obj.save()
            formset.instance = obj
            formset.save()
            changed = update_chart_for_surgery(obj, request.user) if form.cleaned_data.get("update_chart") else 0
            done = complete_plan_for_surgery(obj)
        message = _("Surgery %(number)s saved.") % {"number": obj.number}
        if changed:
            message += " " + _("Dental chart updated for %(n)s teeth.") % {"n": changed}
        if done:
            message += " " + _("%(n)s treatment plan items marked as done.") % {"n": len(done)}
        messages.success(request, message)
        return redirect(obj)
    return render(request, "surgery/surgery_form.html", {
        "form": form, "formset": formset, "surgery": surgery,
        "title": _("Edit surgery chart") if surgery else _("New surgery chart"),
        "procedures": SurgerySite.PROCEDURES,
    })


def surgery_detail(request, pk):
    surgery = get_object_or_404(
        Surgery.objects.select_related("patient", "instructor", "operator_1", "operator_2", "assistant"), pk=pk
    )
    get_clinical_patient_or_403(request.user, surgery.patient_id)
    sites = list(surgery.sites.select_related("implant_system"))
    return render(request, "surgery/surgery_detail.html", {
        "surgery": surgery, "sites": sites, "procedures": SurgerySite.PROCEDURES,
        "photos": surgery.photos.select_related("photo_type"),
        "can_edit": _can_edit_surgery(request.user, surgery),
        "print": request.GET.get("print") == "1",
    })


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
    return render(request, "surgery/implant_detail.html", {"site": site, "patient": patient, "form": form})


# ------------------------------------------------------------ case finder
QUICK_SEARCHES = [
    (_("Healing - waiting 2nd stage"), {"status": "placed"}),
    (_("Uncovered - waiting impression / scan"), {"status": "uncovered"}),
    (_("Impression taken - waiting delivery"), {"status": "impression"}),
    (_("Loaded implants"), {"status": "loaded"}),
    (_("Failed implants"), {"status": "failed"}),
    (_("Sinus lift cases"), {"procedures_any": ["open_sinus", "closed_sinus"], "result": "sites"}),
    (_("GBR / block graft cases"), {"procedures_any": "gbr", "result": "sites"}),
    (_("Immediate implants"), {"procedures_any": "immediate_implant"}),
]


@role_required(*MANAGEMENT)
def finder(request):
    form = FinderForm(request.GET or None)
    data = form.cleaned_data if form.is_bound and form.is_valid() else {}
    sites = filter_sites(data)
    facts = SiteFacts(sites)
    if request.GET.get("export") == "csv":
        return export_csv(facts, filename="cia-cases.csv")
    overall, groups = statistics(facts, data.get("group_by", ""), data.get("group_by_2", ""))
    params = request.GET.copy()
    for key in ("page", "export"):
        params.pop(key, None)
    page = Paginator(facts.sites, 50).get_page(request.GET.get("page"))
    saved = SavedSearch.objects.filter(Q(owner=request.user) | Q(shared=True))
    quick = [(label, urlencode(query, doseq=True)) for label, query in QUICK_SEARCHES]
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
    return render(request, "surgery/finder.html", {
        "call_rows": call_rows,
        "call_title": call_title,
        "form": form, "page_obj": page, "overall": overall, "groups": groups, "query": params.urlencode(),
        "saved": saved, "quick": quick, "group_label": dict(form.fields["group_by"].choices).get(data.get("group_by")),
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
