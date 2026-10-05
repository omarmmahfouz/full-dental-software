"""Restorative work: finder and statistics (round 13), apart from the implant case finder (apps/surgery/finder.py).
Every step of the treatment log that is not surgery or records (fillings, root canals, crowns and bridges, teeth on
implants, dentures, gums, orthodontics…), filtered by the work, the teeth, the dentist and the patient, then grouped
for statistics; and the prostheses on implants by kind, material, retention and stage."""

import csv
from collections import defaultdict

from django import forms
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.charting.teeth import SPAN_CHOICES, is_anterior, jaw, parse_teeth, span_kind, span_label, tooth_type
from apps.core.forms import StyledForm
from apps.core.mixins import role_required
from apps.core.roles import MANAGEMENT
from apps.core.utils import age_from_birth_date
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.models import Gender, Patient

from .models import StepGroup, TreatmentStep, TreatmentStepType

# The kinds of work that are restorative (surgery and the records have their own finder and pages).
RESTORATIVE_GROUPS = [code for code, _label in StepGroup.choices
                      if code not in (StepGroup.SURGERY, StepGroup.IMPLANT_SURGERY, StepGroup.RECORDS)]

GROUP_CHOICES = [
    ("", _("No grouping")),
    ("group", _("Kind of work")),
    ("step", _("Step")),
    ("operator", _("Operator")),
    ("operator_kind", _("Operator type")),
    ("material", _("Material")),
    ("span", _("Single crown, bridge or full arch")),
    ("jaw", _("Jaw")),
    ("region", _("Anterior / posterior")),
    ("tooth_type", _("Tooth type")),
    ("tooth", _("Tooth")),
    ("checked", _("Checked by a supervisor")),
    ("grade", _("Grade")),
    ("gender", _("Gender")),
    ("age_group", _("Age group")),
    ("year", _("Year")),
    ("month", _("Month")),
]
# One tap groups the results (the filters stay).
QUICK_GROUPS = [("group", _("Kind of work")), ("step", _("Step")), ("span", _("Single crown, bridge or full arch")),
                ("operator", _("Operator")),
                ("material", _("Material")), ("tooth_type", _("Tooth type")), ("month", _("Month"))]


class RestorativeFinderForm(StyledForm):
    date_from = forms.DateField(label=_("done from"), required=False)
    date_to = forms.DateField(label=_("done to"), required=False)
    groups = forms.MultipleChoiceField(label=_("kind of work"), required=False,
                                       choices=[(c, l) for c, l in StepGroup.choices if c in RESTORATIVE_GROUPS],
                                       widget=forms.CheckboxSelectMultiple)
    steps = forms.ModelMultipleChoiceField(label=_("step (any of)"), required=False, queryset=None)
    span = forms.MultipleChoiceField(label=_("single crown, bridge or full arch"), required=False,
                                     choices=SPAN_CHOICES, widget=forms.CheckboxSelectMultiple)
    teeth = forms.CharField(label=_("teeth"), required=False, help_text=_("e.g. 36, 46 or 34-37"))
    jaw = forms.ChoiceField(label=_("jaw"), required=False, choices=[("", _("Any")), ("upper", _("Upper")),
                                                                     ("lower", _("Lower"))])
    region = forms.ChoiceField(label=_("region"), required=False,
                               choices=[("", _("Any")), ("anterior", _("Anterior")), ("posterior", _("Posterior"))])
    material = forms.CharField(label=_("material (contains)"), required=False)
    operator = DentistChoiceField(label=_("operator"), required=False, empty_label=_("Any"))
    operator_kind = forms.ChoiceField(label=_("operator type"), required=False,
                                      choices=[("", _("Any"))] + list(Dentist.Kind.choices))
    checked = forms.ChoiceField(label=_("checked by a supervisor"), required=False,
                                choices=[("", _("Any")), ("yes", _("Yes")), ("no", _("No"))])
    gender = forms.ChoiceField(label=_("gender"), required=False, choices=[("", _("Any"))] + list(Gender.choices))
    age_min = forms.IntegerField(label=_("age from"), required=False, min_value=0, max_value=120)
    age_max = forms.IntegerField(label=_("age to"), required=False, min_value=0, max_value=120)
    group_by = forms.ChoiceField(label=_("statistics by"), required=False, choices=GROUP_CHOICES)
    group_by_2 = forms.ChoiceField(label=_("then by"), required=False, choices=GROUP_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["steps"].queryset = TreatmentStepType.objects.filter(group__in=RESTORATIVE_GROUPS)
        self.fields["steps"].widget.attrs["size"] = 6

    def clean_teeth(self):
        return parse_teeth(self.cleaned_data.get("teeth"))


def _years_ago(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def find_steps(data):
    steps = TreatmentStep.objects.filter(patient__in=Patient.objects.here(),
                                         step_type__group__in=RESTORATIVE_GROUPS).select_related(
        "patient", "step_type", "operator", "verified_by")
    if data.get("date_from"):
        steps = steps.filter(performed_at__date__gte=data["date_from"])
    if data.get("date_to"):
        steps = steps.filter(performed_at__date__lte=data["date_to"])
    if data.get("groups"):
        steps = steps.filter(step_type__group__in=data["groups"])
    if data.get("steps"):
        steps = steps.filter(step_type__in=data["steps"])
    if data.get("material"):
        steps = steps.filter(material__icontains=data["material"])
    if data.get("operator"):
        steps = steps.filter(operator=data["operator"])
    if data.get("operator_kind"):
        steps = steps.filter(operator__kind=data["operator_kind"])
    if data.get("checked") == "yes":
        steps = steps.filter(verified_at__isnull=False)
    elif data.get("checked") == "no":
        steps = steps.filter(verified_at__isnull=True)
    if data.get("gender"):
        steps = steps.filter(patient__gender=data["gender"])
    today = timezone.localdate()
    if data.get("age_min") is not None:
        steps = steps.filter(patient__birth_date__lte=_years_ago(today, data["age_min"]))
    if data.get("age_max") is not None:
        steps = steps.filter(patient__birth_date__gt=_years_ago(today, data["age_max"] + 1))
    steps = list(steps.order_by("-performed_at", "-pk"))
    wanted, wanted_jaw = set(data.get("teeth") or []), data.get("jaw")
    result = []
    for step in steps:
        teeth = _teeth(step)
        if wanted and not wanted & set(teeth):
            continue
        if wanted_jaw and not any(jaw(t) == wanted_jaw for t in teeth):
            continue
        if data.get("region") and not any(is_anterior(t) == (data["region"] == "anterior") for t in teeth):
            continue
        step.span = span_kind(teeth, step.step_type.name_en, step.step_type.group)
        if data.get("span") and step.span not in data["span"]:
            continue
        step.span_label = span_label(step.span)
        step.teeth_list = teeth
        result.append(step)
    return result


def _teeth(step):
    try:
        return [t for t in parse_teeth(step.teeth) if t % 10 in range(1, 9)] if step.teeth else []
    except Exception:  # noqa: BLE001 - an old value that no longer reads counts without teeth
        return []


def values(step, key):
    """The value(s) of one step for a grouping (a step on several teeth counts under each of their kinds)."""
    if key == "group":
        return [step.step_type.get_group_display()]
    if key == "step":
        return [str(step.step_type)]
    if key == "operator":
        return [str(step.operator or "—")]
    if key == "operator_kind":
        return [step.operator.get_kind_display() if step.operator_id else "—"]
    if key == "material":
        return [step.material or "—"]
    if key == "span":
        return [str(getattr(step, "span_label", "") or "—")]
    teeth = getattr(step, "teeth_list", _teeth(step))
    if key == "jaw":
        return sorted({str(_("Upper") if jaw(t) == "upper" else _("Lower")) for t in teeth}) or ["—"]
    if key == "region":
        return sorted({str(_("Anterior") if is_anterior(t) else _("Posterior")) for t in teeth}) or ["—"]
    if key == "tooth_type":
        return sorted({tooth_type(t) for t in teeth}) or ["—"]
    if key == "tooth":
        return [str(t) for t in teeth] or ["—"]
    if key == "checked":
        return [str(_("Checked") if step.verified_at else _("Not checked yet"))]
    if key == "grade":
        return [str(step.grade) if step.grade else "—"]
    if key == "gender":
        return [step.patient.get_gender_display() or "—"]
    if key == "age_group":
        age = age_from_birth_date(step.patient.birth_date, today=timezone.localtime(step.performed_at).date())
        return [f"{age // 10 * 10}-{age // 10 * 10 + 9}" if age is not None else "—"]
    local = timezone.localtime(step.performed_at)
    if key == "year":
        return [str(local.year)]
    if key == "month":
        return [local.strftime("%Y-%m")]
    return ["—"]


def _stats(steps):
    grades = [s.grade for s in steps if s.grade]
    checked = sum(1 for s in steps if s.verified_at)
    return {"steps": len(steps), "teeth": sum(len(getattr(s, "teeth_list", [])) for s in steps),
            "patients": len({s.patient_id for s in steps}), "operators": len({s.operator_id for s in steps}),
            "checked": round(100 * checked / len(steps)) if steps else None,
            "grade": round(sum(grades) / len(grades), 1) if grades else None}


def statistics(steps, group_by="", group_by_2=""):
    overall, groups = _stats(steps), []
    if group_by:
        buckets = defaultdict(list)
        for step in steps:
            for first in values(step, group_by):
                for second in (values(step, group_by_2) if group_by_2 else [""]):
                    buckets[(first, second)].append(step)
        for (first, second), items in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            groups.append({"key": first, "key2": second, **_stats(items)})
    return overall, groups


def by_kind(steps):
    """The steps found by kind of work (the table on top of the page; a click filters by it)."""
    rows = defaultdict(list)
    for step in steps:
        rows[step.step_type.group].append(step)
    order = [code for code, _label in StepGroup.choices]
    return [{"code": code, "label": dict(StepGroup.choices)[code], **_stats(items)}
            for code, items in sorted(rows.items(), key=lambda kv: order.index(kv[0]))]


def prostheses_on_implants(date_from=None, date_to=None):
    """The prostheses on implants of this place: by kind, with their units, how many are delivered, and their
    material and retention."""
    from apps.surgery.models import Prosthesis

    items = Prosthesis.objects.filter(patient__in=Patient.objects.here())
    if date_from:
        items = items.filter(created_at__date__gte=date_from)
    if date_to:
        items = items.filter(created_at__date__lte=date_to)
    rows = {}
    for prosthesis in items.prefetch_related("implants"):
        row = rows.setdefault(prosthesis.kind, {"label": prosthesis.get_kind_display(), "number": 0, "units": 0,
                                                "implants": 0, "delivered": 0, "patients": set(),
                                                "materials": defaultdict(int), "retention": defaultdict(int)})
        row["number"] += 1
        row["units"] += prosthesis.units
        row["implants"] += len(prosthesis.implants.all())
        row["delivered"] += prosthesis.status == Prosthesis.Status.DELIVERED
        row["patients"].add(prosthesis.patient_id)
        if prosthesis.material:
            row["materials"][prosthesis.get_material_display()] += 1
        if prosthesis.retention:
            row["retention"][prosthesis.get_retention_display()] += 1
    order = [kind for kind, _label in Prosthesis.Kind.choices]
    return [{"code": kind, "label": row["label"], "number": row["number"], "units": row["units"],
             "implants": row["implants"], "delivered": row["delivered"], "patients": len(row["patients"]),
             "materials": sorted(row["materials"].items(), key=lambda kv: -kv[1]),
             "retention": sorted(row["retention"].items(), key=lambda kv: -kv[1])}
            for kind, row in sorted(rows.items(), key=lambda kv: order.index(kv[0]))]


@role_required(*MANAGEMENT)
def restorative_finder(request):
    form = RestorativeFinderForm(request.GET or None)
    data = form.cleaned_data if form.is_bound and form.is_valid() else {}
    steps = find_steps(data)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="restorative-work.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["date", "patient_file", "gender", "age", "kind_of_work", "step", "teeth", "surfaces",
                         "prosthesis", "material", "operator", "operator_type", "checked", "grade"])
        for step in steps:
            p = step.patient
            writer.writerow([timezone.localtime(step.performed_at).date().isoformat(), p.file_number, p.gender, p.age,
                             step.step_type.group, step.step_type.name_en or step.step_type, step.teeth,
                             step.surfaces, getattr(step, "span", ""), step.material, step.operator or "",
                             step.operator.kind if step.operator_id else "", "yes" if step.verified_at else "no",
                             step.grade or ""])
        return response
    overall, groups = statistics(steps, data.get("group_by", ""), data.get("group_by_2", ""))
    params = request.GET.copy()
    for key in ("page", "export"):
        params.pop(key, None)
    kinds = by_kind(steps)
    chosen = set(data.get("groups") or [])
    for row in kinds:  # one click filters by that kind of work, a second click removes it
        query = params.copy()
        query.setlist("groups", sorted(chosen ^ {row["code"]}))
        row["active"], row["query"] = row["code"] in chosen, query.urlencode()
    quick = []
    for code, label in QUICK_GROUPS:
        query = params.copy()
        query["group_by"] = code
        query.pop("group_by_2", None)
        quick.append({"label": label, "query": query.urlencode(), "active": data.get("group_by") == code})
    labels = dict(GROUP_CHOICES)
    return render(request, "clinical/restorative_finder.html", {
        "form": form, "page_obj": Paginator(steps, 50).get_page(request.GET.get("page")), "overall": overall,
        "groups": groups, "kinds": kinds, "quick": quick, "query": params.urlencode(),
        "group_label": labels.get(data.get("group_by")), "group_label_2": labels.get(data.get("group_by_2")),
        "prostheses": prostheses_on_implants(data.get("date_from"), data.get("date_to")),
    })
