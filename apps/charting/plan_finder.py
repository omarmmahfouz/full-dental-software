"""Find treatment plans: by case difficulty, planned procedure (e.g. guided surgery),
status, phase, teeth, dentist and patient - and send the patients to the reception to call."""

import csv

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.clinical.models import TreatmentStepType
from apps.core.forms import StyledForm
from apps.core.roles import MANAGEMENT, TEAM_HEAD, has_role
from apps.dentists.forms import DentistChoiceField
from apps.patients.models import Gender
from apps.scheduling.models import Appointment

from .models import PlanItem, TreatmentPlan
from .teeth import parse_teeth

OPEN = [TreatmentPlan.Status.PROPOSED, TreatmentPlan.Status.APPROVED]


class PlanFinderForm(StyledForm):
    status = forms.MultipleChoiceField(label=gettext_lazy("plan status"), required=False,
                                       choices=TreatmentPlan.Status.choices, widget=forms.CheckboxSelectMultiple,
                                       help_text=gettext_lazy("None ticked: open plans (proposed or approved)."))
    difficulty = forms.MultipleChoiceField(label=gettext_lazy("case difficulty"), required=False,
                                           choices=TreatmentPlan.Difficulty.choices, widget=forms.CheckboxSelectMultiple)
    procedures = forms.ModelMultipleChoiceField(label=gettext_lazy("planned procedure (any of)"), required=False,
                                                queryset=TreatmentStepType.objects.filter(is_active=True))
    include_done = forms.BooleanField(label=gettext_lazy("also show procedures already done"), required=False)
    phase = forms.MultipleChoiceField(label=gettext_lazy("phase"), required=False, choices=PlanItem.Phase.choices)
    teeth = forms.CharField(label=gettext_lazy("teeth"), required=False)
    dentist = DentistChoiceField(label=gettext_lazy("planned by"), required=False, empty_label=gettext_lazy("Any"))
    gender = forms.ChoiceField(label=gettext_lazy("gender"), required=False,
                               choices=[("", gettext_lazy("Any"))] + list(Gender.choices))
    age_min = forms.IntegerField(label=gettext_lazy("age from"), required=False, min_value=0, max_value=120)
    age_max = forms.IntegerField(label=gettext_lazy("age to"), required=False, min_value=0, max_value=120)
    created_from = forms.DateField(label=gettext_lazy("planned from"), required=False)
    created_to = forms.DateField(label=gettext_lazy("planned to"), required=False)
    no_appointment = forms.BooleanField(label=gettext_lazy("no upcoming appointment"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["procedures"].widget.attrs["size"] = 8

    def clean_teeth(self):
        return parse_teeth(self.cleaned_data.get("teeth"))


def _years_ago(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def find_plans(data):
    """Returns [(plan, matching planned items)]."""
    plans = TreatmentPlan.objects.select_related("patient", "dentist", "approved_by").prefetch_related("items__step_type")
    plans = plans.filter(status__in=data.get("status") or OPEN)
    if data.get("difficulty"):
        plans = plans.filter(difficulty__in=data["difficulty"])
    if data.get("dentist"):
        plans = plans.filter(dentist=data["dentist"])
    if data.get("created_from"):
        plans = plans.filter(created_at__date__gte=data["created_from"])
    if data.get("created_to"):
        plans = plans.filter(created_at__date__lte=data["created_to"])
    if data.get("gender"):
        plans = plans.filter(patient__gender=data["gender"])
    today = timezone.localdate()
    if data.get("age_min") is not None:
        plans = plans.filter(patient__birth_date__lte=_years_ago(today, data["age_min"]))
    if data.get("age_max") is not None:
        plans = plans.filter(patient__birth_date__gt=_years_ago(today, data["age_max"] + 1))
    if data.get("no_appointment"):
        upcoming = Appointment.objects.filter(
            scheduled_at__gte=timezone.now(), status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED]
        ).values("patient_id")
        plans = plans.exclude(patient_id__in=upcoming)

    pending_only = not data.get("include_done")
    item_filters = bool(data.get("procedures") or data.get("phase") or data.get("teeth"))
    wanted_types = {t.pk for t in data.get("procedures") or []}
    wanted_phases = {int(p) for p in data.get("phase") or []}
    wanted_teeth = set(data.get("teeth") or [])
    results = []
    for plan in plans.order_by("-created_at"):
        items = []
        for item in plan.items.all():
            if item.status == PlanItem.Status.CANCELLED:
                continue
            if pending_only and item.status != PlanItem.Status.PLANNED:
                continue
            if wanted_types and item.step_type_id not in wanted_types:
                continue
            if wanted_phases and item.phase not in wanted_phases:
                continue
            if wanted_teeth and not wanted_teeth & set(parse_teeth(item.teeth) if item.teeth else []):
                continue
            items.append(item)
        if items or not item_filters:
            results.append((plan, items))
    return results


def _summary(items):
    return "; ".join(f"{item.step_type} {item.teeth}".strip() for item in items)


def plan_finder(request):
    if not has_role(request.user, *MANAGEMENT, TEAM_HEAD):
        raise PermissionDenied
    bound = bool(request.GET)
    form = PlanFinderForm(request.GET if bound else None)
    data = form.cleaned_data if bound and form.is_valid() else {}
    results = find_plans(data)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="treatment-plans.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(["file", "patient", "mobile", "gender", "age", "plan", "difficulty", "status", "planned_by",
                         "planned_on", "procedures"])
        for plan, items in results:
            p = plan.patient
            writer.writerow([p.file_number, p.full_name, p.preferred_number, p.gender, p.age, plan.title,
                             plan.difficulty, plan.status, plan.dentist or "", plan.created_at.date().isoformat(),
                             _summary(items)])
        return response
    patient_ids = {plan.patient_id for plan, _items in results}
    upcoming = {}
    for appointment in Appointment.objects.filter(
        patient_id__in=patient_ids, scheduled_at__gte=timezone.now(),
        status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
    ).order_by("-scheduled_at"):
        upcoming[appointment.patient_id] = appointment.scheduled_at
    rows = [(plan, items, _summary(items), upcoming.get(plan.patient_id)) for plan, items in results]
    page = Paginator(rows, 100).get_page(request.GET.get("page"))
    params = request.GET.copy()
    for key in ("page", "export"):
        params.pop(key, None)
    chosen = ", ".join(str(t) for t in data.get("procedures") or [])
    return render(request, "charting/plan_finder.html", {
        "form": form, "page_obj": page, "count": len(rows), "query": params.urlencode(),
        "call_rows": [(plan.patient, summary) for plan, _items, summary, _next in rows],
        "call_title": _("Treatment plans: %(what)s") % {"what": chosen} if chosen else _("Treatment plans"),
    })
