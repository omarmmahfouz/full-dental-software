"""Case finder: filter every documented surgical site / implant by patient, team,
surgery and implant details, then group the results for statistics and export."""

import csv
from collections import defaultdict
from datetime import date
from statistics import mean

from django import forms
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import Course
from apps.charting.models import Examination
from apps.charting.teeth import is_anterior, jaw, parse_teeth, tooth_type
from apps.core.forms import StyledForm
from apps.core.utils import age_from_birth_date
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.models import Gender, MedicalCondition, Patient, ReferralSource

from .models import ImplantSystem, Surgery, SurgerySite

YES_NO = [("", _("Any")), ("yes", _("Yes")), ("no", _("No"))]
PROCEDURE_CHOICES = [(name, label) for name, label in SurgerySite.PROCEDURES]

GROUP_CHOICES = [
    ("", _("No grouping")),
    ("company", _("Implant company")),
    ("system", _("Implant type / line")),
    ("diameter", _("Implant diameter")),
    ("length", _("Implant length")),
    ("jaw", _("Jaw")),
    ("region", _("Anterior / posterior")),
    ("tooth_type", _("Tooth type")),
    ("tooth", _("Tooth")),
    ("procedure", _("Procedure")),
    ("difficulty", _("Case difficulty")),
    ("status", _("Implant status")),
    ("gender", _("Gender")),
    ("age_group", _("Age group")),
    ("smoker", _("Smoker")),
    ("diabetic", _("Diabetic")),
    ("operator", _("Operator 1")),
    ("batch", _("Batch / course")),
    ("instructor", _("Instructor")),
    ("bone_particle", _("Bone particle")),
    ("temporary", _("Temporary")),
    ("year", _("Year")),
    ("month", _("Month")),
]


class FinderForm(StyledForm):
    result = forms.ChoiceField(
        label=_("look at"), required=False,
        choices=[("implants", _("Implants only")), ("sites", _("All surgical sites"))],
    )
    date_from = forms.DateField(label=_("surgery from"), required=False)
    date_to = forms.DateField(label=_("surgery to"), required=False)
    # Patient
    gender = forms.ChoiceField(label=_("gender"), required=False, choices=[("", _("Any"))] + list(Gender.choices))
    age_min = forms.IntegerField(label=_("age from"), required=False, min_value=0, max_value=120)
    age_max = forms.IntegerField(label=_("age to"), required=False, min_value=0, max_value=120)
    smoker = forms.ChoiceField(label=_("smoker"), required=False, choices=YES_NO)
    diabetic = forms.ChoiceField(label=_("diabetic"), required=False, choices=YES_NO)
    conditions = forms.ModelMultipleChoiceField(
        label=_("medical condition (any of)"), required=False, queryset=MedicalCondition.objects.filter(is_active=True)
    )
    governorate = forms.CharField(label=_("governorate"), required=False)
    referral_source = forms.ModelChoiceField(
        label=_("referral source"), required=False, queryset=ReferralSource.objects.all(), empty_label=_("Any")
    )
    # Team
    dentist = DentistChoiceField(label=_("dentist (any role)"), required=False, empty_label=_("Any"))
    operator = DentistChoiceField(label=_("operator 1"), required=False, empty_label=_("Any"))
    dentist_kind = forms.ChoiceField(
        label=_("operator type"), required=False, choices=[("", _("Any"))] + list(Dentist.Kind.choices)
    )
    course = forms.ModelChoiceField(label=_("batch / course"), required=False, queryset=Course.objects.all(), empty_label=_("Any"))
    instructor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("instructor"), required=False, empty_label=_("Any"))
    # Surgery
    difficulty = forms.MultipleChoiceField(label=_("case difficulty"), required=False, choices=Surgery.Difficulty.choices)
    bone_particle = forms.MultipleChoiceField(label=_("bone particle"), required=False, choices=Surgery.Particle.choices)
    block_graft = forms.ChoiceField(label=_("block graft"), required=False, choices=YES_NO)
    block_donor = forms.MultipleChoiceField(label=_("block donor site"), required=False, choices=Surgery.BlockDonor.choices)
    membrane_used = forms.ChoiceField(label=_("membrane"), required=False, choices=YES_NO)
    soft_tissue_graft = forms.MultipleChoiceField(label=_("soft tissue graft"), required=False, choices=Surgery.SoftTissueGraft.choices)
    temporary = forms.MultipleChoiceField(label=_("temporary"), required=False, choices=Surgery.Temporary.choices)
    suture_material = forms.MultipleChoiceField(label=_("suture material"), required=False, choices=Surgery.SutureMaterial.choices)
    # Site
    teeth = forms.CharField(label=_("teeth"), required=False, help_text=_("e.g. 36, 46 or 34-37"))
    jaw = forms.ChoiceField(label=_("jaw"), required=False, choices=[("", _("Any")), ("upper", _("Upper")), ("lower", _("Lower"))])
    region = forms.ChoiceField(label=_("region"), required=False,
                               choices=[("", _("Any")), ("anterior", _("Anterior")), ("posterior", _("Posterior"))])
    tooth_type = forms.ChoiceField(label=_("tooth type"), required=False, choices=[
        ("", _("Any")), ("incisor", _("Incisor")), ("canine", _("Canine")), ("premolar", _("Premolar")), ("molar", _("Molar")),
    ])
    procedures_any = forms.MultipleChoiceField(label=_("procedure (any of)"), required=False, choices=PROCEDURE_CHOICES)
    procedures_all = forms.MultipleChoiceField(label=_("procedure (all of)"), required=False, choices=PROCEDURE_CHOICES)
    # Implant
    company = forms.MultipleChoiceField(label=_("implant company"), required=False, choices=[])
    system = forms.ModelMultipleChoiceField(label=_("implant type / line"), required=False, queryset=ImplantSystem.objects.all())
    diameter_min = forms.DecimalField(label=_("diameter from"), required=False, max_digits=3, decimal_places=1)
    diameter_max = forms.DecimalField(label=_("diameter to"), required=False, max_digits=3, decimal_places=1)
    length_min = forms.DecimalField(label=_("length from"), required=False, max_digits=3, decimal_places=1)
    length_max = forms.DecimalField(label=_("length to"), required=False, max_digits=3, decimal_places=1)
    torque_min = forms.IntegerField(label=_("torque from (Ncm)"), required=False, min_value=0)
    torque_max = forms.IntegerField(label=_("torque to (Ncm)"), required=False, min_value=0)
    subcrestal = forms.ChoiceField(label=_("subcrestal"), required=False, choices=YES_NO)
    status = forms.MultipleChoiceField(label=_("implant status"), required=False, choices=SurgerySite.ImplantStatus.choices)
    group_by = forms.ChoiceField(label=_("statistics by"), required=False, choices=GROUP_CHOICES)
    group_by_2 = forms.ChoiceField(label=_("then by"), required=False, choices=GROUP_CHOICES)

    SECTIONS = [
        (_("What and when"), ["result", "date_from", "date_to", "group_by", "group_by_2"]),
        (_("Patient"), ["gender", "age_min", "age_max", "smoker", "diabetic", "conditions", "governorate", "referral_source"]),
        (_("Team"), ["dentist", "operator", "dentist_kind", "course", "instructor"]),
        (_("Site and procedure"), ["teeth", "jaw", "region", "tooth_type", "procedures_any", "procedures_all"]),
        (_("Implant"), ["company", "system", "diameter_min", "diameter_max", "length_min", "length_max",
                        "torque_min", "torque_max", "subcrestal", "status"]),
        (_("Surgery details"), ["difficulty", "bone_particle", "block_graft", "block_donor", "membrane_used",
                                "soft_tissue_graft", "temporary", "suture_material"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        companies = ImplantSystem.objects.order_by("company").values_list("company", flat=True).distinct()
        self.fields["company"].choices = [(c, c) for c in companies]
        for field in self.fields.values():
            if isinstance(field.widget, forms.SelectMultiple):
                field.widget.attrs["size"] = 4

    def sections(self):
        return [(title, [self[name] for name in names]) for title, names in self.SECTIONS]

    def clean_teeth(self):
        return parse_teeth(self.cleaned_data.get("teeth"))


def _flag_patient_ids(condition_word=None, smoker=False):
    """Patients flagged by their examination or by what they told the secretary."""
    if smoker:
        exam_ids = Examination.objects.filter(smoker=True).values_list("patient_id", flat=True)
        told_ids = Patient.objects.filter(medical_conditions__name_en__iexact="Smoker").values_list("pk", flat=True)
    else:
        exam_ids = Examination.objects.filter(conditions__name_en__icontains=condition_word).values_list("patient_id", flat=True)
        told_ids = Patient.objects.filter(medical_conditions__name_en__icontains=condition_word).values_list("pk", flat=True)
    return set(exam_ids) | set(told_ids)


def _years_ago(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def filter_sites(data):
    qs = SurgerySite.objects.select_related(
        "surgery__patient", "surgery__operator_1__candidate", "surgery__operator_2", "surgery__assistant",
        "surgery__instructor", "implant_system",
    )
    if data.get("result", "implants") != "sites":
        qs = qs.exclude(implant_status="")
    if data.get("date_from"):
        qs = qs.filter(surgery__date__gte=data["date_from"])
    if data.get("date_to"):
        qs = qs.filter(surgery__date__lte=data["date_to"])
    # patient
    if data.get("gender"):
        qs = qs.filter(surgery__patient__gender=data["gender"])
    today = timezone.localdate()
    if data.get("age_min") is not None:
        qs = qs.filter(surgery__patient__birth_date__lte=_years_ago(today, data["age_min"]))
    if data.get("age_max") is not None:
        qs = qs.filter(surgery__patient__birth_date__gt=_years_ago(today, data["age_max"] + 1))
    for key, ids in (("smoker", lambda: _flag_patient_ids(smoker=True)), ("diabetic", lambda: _flag_patient_ids("diabet"))):
        if data.get(key) == "yes":
            qs = qs.filter(surgery__patient_id__in=ids())
        elif data.get(key) == "no":
            qs = qs.exclude(surgery__patient_id__in=ids())
    if data.get("conditions"):
        chosen = list(data["conditions"])
        qs = qs.filter(
            Q(surgery__patient__medical_conditions__in=chosen) | Q(surgery__patient__examinations__conditions__in=chosen)
        )
    if data.get("governorate"):
        qs = qs.filter(surgery__patient__governorate__icontains=data["governorate"])
    if data.get("referral_source"):
        qs = qs.filter(surgery__patient__referral_source=data["referral_source"])
    # team
    if data.get("dentist"):
        d = data["dentist"]
        qs = qs.filter(Q(surgery__operator_1=d) | Q(surgery__operator_2=d) | Q(surgery__assistant=d) | Q(surgery__instructor=d))
    if data.get("operator"):
        qs = qs.filter(surgery__operator_1=data["operator"])
    if data.get("dentist_kind"):
        qs = qs.filter(surgery__operator_1__kind=data["dentist_kind"])
    if data.get("course"):
        qs = qs.filter(surgery__operator_1__candidate__enrollments__course=data["course"])
    if data.get("instructor"):
        qs = qs.filter(surgery__instructor=data["instructor"])
    # surgery
    for key in ("difficulty", "bone_particle", "block_donor", "soft_tissue_graft", "temporary", "suture_material"):
        if data.get(key):
            qs = qs.filter(**{f"surgery__{key}__in": data[key]})
    for key in ("block_graft", "membrane_used"):
        if data.get(key):
            qs = qs.filter(**{f"surgery__{key}": data[key] == "yes"})
    # site
    if data.get("teeth"):
        qs = qs.filter(tooth__in=data["teeth"])
    if data.get("jaw"):
        qs = qs.filter(tooth__in=[t for t in range(11, 49) if jaw(t) == data["jaw"] and t % 10 in range(1, 9)])
    if data.get("region"):
        wanted = data["region"] == "anterior"
        qs = qs.filter(tooth__in=[t for t in range(11, 49) if t % 10 in range(1, 9) and is_anterior(t) == wanted])
    if data.get("tooth_type"):
        qs = qs.filter(tooth__in=[t for t in range(11, 49) if t % 10 in range(1, 9) and tooth_type(t) == data["tooth_type"]])
    if data.get("procedures_any"):
        any_q = Q()
        for name in data["procedures_any"]:
            any_q |= Q(**{name: True})
        qs = qs.filter(any_q)
    for name in data.get("procedures_all") or []:
        qs = qs.filter(**{name: True})
    # implant
    if data.get("company"):
        qs = qs.filter(implant_system__company__in=data["company"])
    if data.get("system"):
        qs = qs.filter(implant_system__in=data["system"])
    for key, lookup in (("diameter_min", "implant_diameter__gte"), ("diameter_max", "implant_diameter__lte"),
                        ("length_min", "implant_length__gte"), ("length_max", "implant_length__lte"),
                        ("torque_min", "insertion_torque__gte"), ("torque_max", "insertion_torque__lte")):
        if data.get(key) is not None:
            qs = qs.filter(**{lookup: data[key]})
    if data.get("subcrestal"):
        qs = qs.filter(subcrestal=data["subcrestal"] == "yes")
    if data.get("status"):
        qs = qs.filter(implant_status__in=data["status"])
    return qs.distinct().order_by("-surgery__date", "surgery__pk", "tooth")


class SiteFacts:
    """Per-site values used for grouping and export (computed once)."""

    def __init__(self, sites):
        self.sites = list(sites)
        patient_ids = {s.surgery.patient_id for s in self.sites}
        self.smokers = _flag_patient_ids(smoker=True) & patient_ids
        self.diabetics = _flag_patient_ids("diabet") & patient_ids
        self.batches = {}
        for s in self.sites:
            op = s.surgery.operator_1
            if op.candidate_id and op.pk not in self.batches:
                enrollment = op.candidate.current_enrollment
                self.batches[op.pk] = enrollment.course.code if enrollment else ""

    def age(self, site):
        return age_from_birth_date(site.surgery.patient.birth_date, today=site.surgery.date)

    def values(self, site, key):
        s = site.surgery
        if key == "company":
            return [site.implant_system.company if site.implant_system_id else "—"]
        if key == "system":
            return [str(site.implant_system) if site.implant_system_id else "—"]
        if key == "diameter":
            return [site.diameter_mm or "—"]
        if key == "length":
            return [site.length_mm or "—"]
        if key == "jaw":
            return [str(_("Upper") if jaw(site.tooth) == "upper" else _("Lower"))]
        if key == "region":
            return [str(_("Anterior") if is_anterior(site.tooth) else _("Posterior"))]
        if key == "tooth_type":
            return [tooth_type(site.tooth)]
        if key == "tooth":
            return [str(site.tooth)]
        if key == "procedure":
            return site.procedure_labels() or ["—"]
        if key == "difficulty":
            return [s.get_difficulty_display()]
        if key == "status":
            return [site.get_implant_status_display() or "—"]
        if key == "gender":
            return [s.patient.get_gender_display() or "—"]
        if key == "age_group":
            age = self.age(site)
            return [f"{age // 10 * 10}-{age // 10 * 10 + 9}" if age is not None else "—"]
        if key == "smoker":
            return [str(_("Smoker") if s.patient_id in self.smokers else _("Non-smoker"))]
        if key == "diabetic":
            return [str(_("Diabetic") if s.patient_id in self.diabetics else _("Not diabetic"))]
        if key == "operator":
            return [str(s.operator_1)]
        if key == "batch":
            return [self.batches.get(s.operator_1_id) or "—"]
        if key == "instructor":
            return [str(s.instructor or "—")]
        if key == "bone_particle":
            return [s.get_bone_particle_display() or "—"]
        if key == "temporary":
            return [s.get_temporary_display() or "—"]
        if key == "year":
            return [str(s.date.year)]
        if key == "month":
            return [s.date.strftime("%Y-%m")]
        return ["—"]


def _stats(sites):
    implants = [s for s in sites if s.implant_status]
    failed = sum(1 for s in implants if s.implant_status == SurgerySite.ImplantStatus.FAILED)
    loaded = sum(1 for s in implants if s.implant_status == SurgerySite.ImplantStatus.LOADED)
    days = [s.days_to_loading for s in implants if s.days_to_loading is not None]
    torques = [s.insertion_torque for s in implants if s.insertion_torque]
    return {
        "sites": len(sites),
        "implants": len(implants),
        "patients": len({s.surgery.patient_id for s in sites}),
        "failed": failed,
        "survival": round(100 * (len(implants) - failed) / len(implants), 1) if implants else None,
        "loaded": loaded,
        "waiting": len(implants) - failed - loaded,
        "days_to_loading": round(mean(days)) if days else None,
        "torque": round(mean(torques)) if torques else None,
    }


def statistics(facts, group_by="", group_by_2=""):
    overall = _stats(facts.sites)
    groups = []
    if group_by:
        buckets = defaultdict(list)
        for site in facts.sites:
            for first in facts.values(site, group_by):
                if group_by_2:
                    for second in facts.values(site, group_by_2):
                        buckets[(first, second)].append(site)
                else:
                    buckets[(first, "")].append(site)
        for (first, second), items in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            groups.append({"key": first, "key2": second, **_stats(items)})
    return overall, groups


def export_csv(facts, filename="cases.csv"):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # so Excel opens Arabic text correctly
    writer = csv.writer(response)
    writer.writerow([
        "surgery", "date", "patient_file", "gender", "age_at_surgery", "smoker", "diabetic", "tooth", "jaw", "region",
        "tooth_type", "procedures", "implant_company", "implant_line", "diameter", "length", "lot", "torque_ncm",
        "isq", "subcrestal", "difficulty", "bone_particle", "autogenous_percent", "block_graft", "block_donor",
        "membrane", "membrane_material", "sinus_approach", "soft_tissue_graft", "suture", "temporary",
        "operator_1", "operator_1_type", "batch", "operator_2", "assistant", "instructor", "implant_status",
        "uncovered_on", "impression_on", "loaded_on", "days_to_loading", "failed_on", "failure_reason",
    ])
    for site in facts.sites:
        s, p = site.surgery, site.surgery.patient
        writer.writerow([
            s.number, s.date.isoformat(), p.file_number, p.gender, facts.age(site),
            "yes" if p.pk in facts.smokers else "no", "yes" if p.pk in facts.diabetics else "no",
            site.tooth, jaw(site.tooth), "anterior" if is_anterior(site.tooth) else "posterior", tooth_type(site.tooth),
            "; ".join(name for name, _label in SurgerySite.PROCEDURES if getattr(site, name)),
            site.implant_system.company if site.implant_system_id else "",
            site.implant_system.line if site.implant_system_id else "",
            site.diameter_mm, site.length_mm, site.lot_number, site.insertion_torque or "",
            site.isq or "", "yes" if site.subcrestal else "no", s.difficulty, s.bone_particle,
            s.autogenous_percent if s.autogenous_percent is not None else "", "yes" if s.block_graft else "no",
            s.block_donor, "yes" if s.membrane_used else "no", s.membrane_material, s.sinus_approach,
            s.soft_tissue_graft, f"{s.suture_size} {s.suture_material}".strip(), s.temporary,
            s.operator_1.full_name, s.operator_1.kind, facts.batches.get(s.operator_1_id, ""),
            s.operator_2.full_name if s.operator_2_id else "", s.assistant.full_name if s.assistant_id else "",
            s.instructor.full_name if s.instructor_id else "", site.implant_status,
            site.uncovered_on or "", site.impression_on or "", site.loaded_on or "",
            site.days_to_loading if site.days_to_loading is not None else "", site.failed_on or "", site.failure_reason,
        ])
    return response
