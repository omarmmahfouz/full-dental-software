"""The life of an implant after its surgery (round 15): each check (the findings and the class of the tissues
around it) and each complication in detail (its group, kind, when it showed, the nerve for a paresthesia, the
treatment and how it ended). A finder lists them all for the follow-up and for papers, with an Excel file."""

import tempfile
from collections import Counter

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.charting.models import ToothChange
from apps.charting.rules import apply_changes, plan_changes
from apps.clinical.models import ChartEffect, TreatmentStep
from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, MANAGEMENT, has_role
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403

from .forms import ComplicationFilterForm, ImplantComplicationForm, ImplantFollowUpForm
from .models import ImplantComplication, ImplantFollowUp, SurgerySite


def _site(request, pk):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    site = get_object_or_404(SurgerySite.objects.select_related("surgery__patient", "implant_system"), pk=pk)
    get_clinical_patient_or_403(request.user, site.surgery.patient_id)
    return site


def _step(request, site):
    """The treatment step the check or the complication was recorded with (``?step=``), if it is this patient's."""
    pk = request.GET.get("step") or request.POST.get("step") or ""
    if pk.isdigit():
        return TreatmentStep.objects.filter(pk=pk, patient_id=site.surgery.patient_id).first()
    return None


def mark_failed(site, when, reason, user):
    """An implant removed or lost: failed on the chart (the tooth becomes missing), once."""
    if site.implant_status == SurgerySite.ImplantStatus.FAILED:
        return False
    site.advance(SurgerySite.ImplantStatus.FAILED, on=when)
    site.failure_reason = (site.failure_reason or reason)[:255]
    site.save(update_fields=["implant_status", "failed_on", "failure_reason"])
    patient = site.surgery.patient
    apply_changes(patient, plan_changes(patient, ChartEffect.IMPLANT_FAILED, [site.tooth]), user,
                  ToothChange.Source.MANUAL)
    return True


def implant_check(request, pk, check_pk=None):
    """Write (or correct) a check of an implant."""
    site = _site(request, pk)
    check = get_object_or_404(ImplantFollowUp, pk=check_pk, site=site) if check_pk else None
    me = Dentist.for_user(request.user)
    form = ImplantFollowUpForm(request.POST or None, instance=check,
                               initial={"dentist": me, "checked_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        check = form.save(commit=False)
        check.site, check.patient = site, site.surgery.patient
        if check.pk is None:
            check.created_by = request.user
            check.treatment_step = _step(request, site)
        if "status" not in form.changed_data and check_pk:
            check.status = ""  # corrected findings: the class is found again
        check.save()
        messages.success(request, _("Check of implant %(tooth)s saved: %(status)s.")
                         % {"tooth": site.tooth, "status": check.get_status_display()})
        return redirect("surgery:implant", pk=site.pk)
    return render(request, "surgery/implant_record_form.html", {
        "site": site, "patient": site.surgery.patient, "form": form, "step": _step(request, site),
        "title": _("Check of implant %(tooth)s") % {"tooth": site.tooth}})


def implant_complication(request, pk, complication_pk=None):
    """Write (or follow) a complication of an implant. A removal or a lost implant makes it failed on the chart."""
    site = _site(request, pk)
    complication = get_object_or_404(ImplantComplication, pk=complication_pk, site=site) if complication_pk else None
    me = Dentist.for_user(request.user)
    initial = {"dentist": me, "found_on": timezone.localdate()}
    if request.GET.get("kind") in ImplantComplication.KIND_GROUP:
        initial["kind"] = request.GET["kind"]
    form = ImplantComplicationForm(request.POST or None, instance=complication, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            complication = form.save(commit=False)
            complication.site, complication.patient = site, site.surgery.patient
            if complication.pk is None:
                complication.created_by = request.user
                complication.treatment_step = _step(request, site)
            complication.save()
            lost = complication.treatment == ImplantComplication.Treatment.IMPLANT_REMOVED or \
                complication.outcome == ImplantComplication.Outcome.IMPLANT_LOST
            if lost and mark_failed(site, complication.resolved_on or complication.found_on,
                                    complication.get_kind_display(), request.user):
                messages.warning(request, _("Implant %(tooth)s is marked failed and the tooth missing on the chart.")
                                 % {"tooth": site.tooth})
        messages.success(request, _("Complication of implant %(tooth)s saved.") % {"tooth": site.tooth})
        return redirect("surgery:implant", pk=site.pk)
    return render(request, "surgery/implant_record_form.html", {
        "site": site, "patient": site.surgery.patient, "form": form, "step": _step(request, site),
        "title": (_("Complication of implant %(tooth)s") % {"tooth": site.tooth})})


def patient_implants(request, patient_pk):
    """The patient's implants, to choose the one checked or with a complication (from the file's Record menu)."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    sites = [s for s in SurgerySite.objects.filter(surgery__patient=patient).select_related(
        "surgery", "implant_system").prefetch_related("complications", "follow_ups").order_by("tooth")
        if s.has_implant]
    return render(request, "surgery/patient_implants.html", {"patient": patient, "sites": sites})


def _filtered(request):
    form = ComplicationFilterForm(request.GET or None)
    rows = ImplantComplication.objects.filter(patient__branch=branch_for_user(request.user)).select_related(
        "site__surgery__operator_1", "site__implant_system", "site__operator", "patient", "dentist")
    if form.is_valid():
        data = form.cleaned_data
        if data.get("date_from"):
            rows = rows.filter(found_on__gte=data["date_from"])
        if data.get("date_to"):
            rows = rows.filter(found_on__lte=data["date_to"])
        for name in ("group", "kind", "timing", "outcome"):
            if data.get(name):
                rows = rows.filter(**{name: data[name]})
        if data.get("system"):
            rows = rows.filter(site__implant_system=data["system"])
        if data.get("operator"):
            rows = rows.filter(site__in=SurgerySite.objects.done_by(data["operator"]))
    return form, rows


@role_required(*MANAGEMENT, "team_head")
def complications(request):
    """Every complication of the implants of this place, by group and kind, for the follow-up and for papers."""
    form, rows = _filtered(request)
    rows = list(rows[:2000])
    if request.GET.get("excel"):
        return _excel(rows)
    groups = dict(ImplantComplication.Group.choices)
    kinds = dict(ImplantComplication.KIND_CHOICES)
    by_group = Counter(row.group for row in rows)
    by_kind = Counter(row.kind for row in rows)
    implants = SurgerySite.objects.filter(surgery__branch=branch_for_user(request.user)).exclude(implant_status="")
    total_implants = implants.count()
    checks = ImplantFollowUp.objects.filter(patient__branch=branch_for_user(request.user))
    by_status = Counter(checks.values_list("status", flat=True))
    return render(request, "surgery/complications.html", {
        "form": form, "rows": rows, "total_implants": total_implants,
        "by_group": [(groups.get(code, code), n, round(100 * n / total_implants, 1) if total_implants else 0)
                     for code, n in by_group.most_common()],
        "by_kind": [(kinds.get(code, code), n) for code, n in by_kind.most_common(12)],
        "patients": len({row.patient_id for row in rows}), "implants": len({row.site_id for row in rows}),
        "open": sum(1 for row in rows if row.outcome in ("open", "improving")),
        "by_status": [(label, by_status.get(code, 0)) for code, label in
                      ImplantFollowUp._meta.get_field("status").choices if by_status.get(code)],
        "query": request.GET.urlencode(),
    })


def _excel(rows):
    """The complications as an Excel file, one line each, with the implant and the dates (for papers)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from apps.core.backup import _excel_safe

    book = Workbook()
    sheet = book.active
    sheet.title = "Complications"
    head = [_("patient file"), _("tooth"), _("implant type"), _("diameter"), _("length"), _("surgery date"),
            _("operator"), _("loaded on"), _("group"), _("complication"), _("found on"), _("months after surgery"),
            _("when it showed"), _("severity"), _("nerve"), _("side"), _("area felt (lip, chin, tongue, cheek...)"),
            _("treatment"), _("outcome"), _("resolved / ended on"), _("days to resolve"), _("signs"), _("cause"),
            _("notes")]
    sheet.append([str(h) for h in head])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        site = row.site
        sheet.append([_excel_safe(value) for value in (
            row.patient.file_number, site.tooth, str(site.implant_system or ""), site.diameter_mm, site.length_mm,
            site.surgery.date, str(site.done_by or ""), site.loaded_on, row.get_group_display(),
            row.get_kind_display(), row.found_on, row.months_since_placement, row.get_timing_display(),
            row.get_severity_display(), row.get_nerve_display(), row.get_side_display(), row.area,
            row.get_treatment_display(), row.get_outcome_display(), row.resolved_on, row.days_to_resolve, row.signs,
            row.cause, row.notes)])
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 18
    output = tempfile.TemporaryFile()
    book.save(output)
    output.seek(0)
    return FileResponse(output, as_attachment=True,
                        filename=f"implant-complications-{timezone.localdate():%Y-%m-%d}.xlsx")
