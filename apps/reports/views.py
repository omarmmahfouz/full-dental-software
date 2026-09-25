"""Management statistics. Figures are computed in Python over the chosen period,
which is simple, database-independent and fast enough for a clinic's volume."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean

from django import forms
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import Course, Enrollment, Payment, PaymentMethod
from apps.clinical.models import LabRequest, TreatmentStep
from apps.complaints.models import Complaint
from apps.core.forms import DateRangeForm
from apps.core.mixins import role_required
from apps.core.models import ClinicSettings
from apps.dentists.models import Dentist
from apps.core.roles import MANAGEMENT, OWNER, TEAM_HEAD, has_role
from apps.patients.models import Lead, Patient
from apps.purchasing.models import PurchaseCategory, PurchaseItem
from apps.scheduling.models import Appointment, RoomShift, day_bounds
from apps.surgery.models import Surgery, SurgerySite


def _period(request, default_days=30):
    form = DateRangeForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today - timedelta(days=default_days - 1), today
    if form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    if not form.is_bound:
        form = DateRangeForm(initial={"date_from": date_from, "date_to": date_to})
    start, _end = day_bounds(date_from)
    _start, end = day_bounds(date_to)
    return form, date_from, date_to, start, end


def _avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values)) if values else None


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


@role_required(*MANAGEMENT, TEAM_HEAD)
def index(request):
    return render(request, "reports/index.html")


@role_required(*MANAGEMENT)
def visits_report(request):
    """Punctuality, waiting, chair time and total stay."""
    form, date_from, date_to, start, end = _period(request)
    threshold = ClinicSettings.get().late_threshold_minutes
    appointments = list(
        Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end).select_related("patient", "dentist", "room")
    )
    booked = [a for a in appointments if not a.is_walk_in]
    arrived = [a for a in appointments if a.arrived_at]
    booked_arrived = [a for a in booked if a.arrived_at]
    late = [a for a in booked_arrived if a.is_late]
    summary = {
        "total": len(appointments),
        "booked": len(booked),
        "walk_in": len(appointments) - len(booked),
        "arrived": len(arrived),
        "no_show": sum(a.status == Appointment.Status.NO_SHOW for a in appointments),
        "cancelled": sum(a.status == Appointment.Status.CANCELLED for a in appointments),
        "late": len(late),
        "late_pct": _pct(len(late), len(booked_arrived)),
        "avg_late": _avg(a.late_minutes for a in late),
        "avg_wait": _avg(a.waiting_minutes for a in arrived),
        "avg_chair": _avg(a.chair_minutes for a in arrived),
        "avg_total": _avg(a.total_minutes for a in arrived),
    }

    def group(key):
        groups = defaultdict(list)
        for appointment in appointments:
            groups[key(appointment)].append(appointment)
        rows = []
        for name, items in groups.items():
            came = [a for a in items if a.arrived_at]
            came_booked = [a for a in came if not a.is_walk_in]
            late_items = [a for a in came_booked if a.is_late]
            rows.append({
                "name": name or "—",
                "visits": len(came),
                "no_show": sum(a.status == Appointment.Status.NO_SHOW for a in items),
                "late_pct": _pct(len(late_items), len(came_booked)),
                "avg_wait": _avg(a.waiting_minutes for a in came),
                "avg_chair": _avg(a.chair_minutes for a in came),
                "chair_total": sum(a.chair_minutes or 0 for a in came),
            })
        return sorted(rows, key=lambda r: -r["visits"])

    return render(
        request,
        "reports/visits.html",
        {
            "form": form, "date_from": date_from, "date_to": date_to, "threshold": threshold,
            "summary": summary,
            "by_dentist": group(lambda a: str(a.dentist) if a.dentist else None),
            "by_room": group(lambda a: str(a.room) if a.room else None),
            "late_list": sorted(late, key=lambda a: -a.late_minutes)[:50],
            "long_waits": sorted([a for a in arrived if (a.waiting_minutes or 0) > 30], key=lambda a: -a.waiting_minutes)[:30],
        },
    )


class DentistReportForm(DateRangeForm):
    kind = forms.ChoiceField(label=_("type"), required=False, choices=[("", _("All"))] + list(Dentist.Kind.choices))
    course = forms.ModelChoiceField(label=_("batch / course"), queryset=Course.objects.all(), required=False,
                                    empty_label=_("All"))

    def __init__(self, *args, team_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if team_only:
            del self.fields["course"]
            self.fields["kind"].choices = [c for c in self.fields["kind"].choices if c[0] != Dentist.Kind.CANDIDATE]


@role_required(*MANAGEMENT, TEAM_HEAD)
def dentists_report(request):
    """What each dentist did: treatments, checks, grades, surgeries, implants, lab work, patients, hours.
    The head of the CIA dentists team sees the CIA dentists only, not the course candidates."""
    form, date_from, date_to, start, end = _period(request)
    team_only = not has_role(request.user, *MANAGEMENT)
    extra = DentistReportForm(request.GET or None, team_only=team_only)
    dentists = Dentist.objects.active().select_related("candidate")
    if team_only:
        dentists = dentists.exclude(kind=Dentist.Kind.CANDIDATE)
    if extra.is_valid():
        if extra.cleaned_data.get("kind"):
            dentists = dentists.filter(kind=extra.cleaned_data["kind"])
        if extra.cleaned_data.get("course"):
            dentists = dentists.filter(candidate__enrollments__course=extra.cleaned_data["course"])
    dentists = list(dentists)
    steps = TreatmentStep.objects.filter(performed_at__gte=start, performed_at__lt=end)
    step_stats = {
        row["operator"]: row
        for row in steps.values("operator").annotate(
            n=Count("id"), checked=Count("id", filter=Q(verified_at__isnull=False)), grade=Avg("grade")
        )
    }
    matrix = defaultdict(lambda: defaultdict(int))
    step_names = {}
    lang_en = (request.LANGUAGE_CODE or "").startswith("en")
    for row in steps.values("operator", "step_type", "step_type__name_ar", "step_type__name_en").annotate(n=Count("id")):
        matrix[row["operator"]][row["step_type"]] = row["n"]
        step_names[row["step_type"]] = (
            row["step_type__name_en"] if row["step_type__name_en"] and lang_en else row["step_type__name_ar"]
        )
    surgeries = Surgery.objects.filter(date__range=(date_from, date_to))
    surgeries_op1 = dict(surgeries.values_list("operator_1").annotate(n=Count("id")))
    surgeries_op2 = dict(surgeries.exclude(operator_2=None).values_list("operator_2").annotate(n=Count("id")))
    sites = SurgerySite.objects.filter(surgery__date__range=(date_from, date_to)).exclude(implant_status="")
    implants = dict(sites.values_list("surgery__operator_1").annotate(n=Count("id")))
    failed = dict(sites.filter(implant_status=SurgerySite.ImplantStatus.FAILED)
                  .values_list("surgery__operator_1").annotate(n=Count("id")))
    all_time_implants = dict(
        SurgerySite.objects.exclude(implant_status="").values_list("surgery__operator_1").annotate(n=Count("id"))
    )
    labs = dict(
        LabRequest.objects.filter(created_at__gte=start, created_at__lt=end).values_list("dentist").annotate(n=Count("id"))
    )
    remakes = dict(
        LabRequest.objects.filter(created_at__gte=start, created_at__lt=end, remake_count__gt=0)
        .values_list("dentist").annotate(n=Count("id"))
    )
    patients = dict(
        Patient.objects.filter(status=Patient.Status.ACTIVE).values_list("assigned_dentist").annotate(n=Count("id"))
    )
    complaints = dict(
        Complaint.objects.filter(created_at__gte=start, created_at__lt=end)
        .values_list("concerned_dentist").annotate(n=Count("id"))
    )
    shift_minutes = defaultdict(int)
    for shift in RoomShift.objects.filter(date__range=(date_from, date_to)):
        minutes = (datetime.combine(shift.date, shift.end_time) - datetime.combine(shift.date, shift.start_time)).seconds // 60
        shift_minutes[shift.dentist_id] += minutes
    chair = defaultdict(int)
    no_shows = defaultdict(int)
    for appointment in Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end, dentist__isnull=False):
        chair[appointment.dentist_id] += appointment.chair_minutes or 0
        no_shows[appointment.dentist_id] += appointment.status == Appointment.Status.NO_SHOW

    step_types = sorted(step_names.items(), key=lambda item: item[1])
    rows = []
    for dentist in dentists:
        stats = step_stats.get(dentist.pk, {})
        required = remaining = None
        if dentist.candidate_id:
            enrollment = dentist.candidate.current_enrollment
            if enrollment is not None and enrollment.implants_required:
                required = enrollment.implants_required
                remaining = max(required - all_time_implants.get(dentist.pk, 0), 0)
        rows.append({
            "dentist": dentist,
            "steps": stats.get("n", 0),
            "checked": stats.get("checked", 0),
            "grade": round(stats["grade"], 1) if stats.get("grade") else None,
            "surgeries": surgeries_op1.get(dentist.pk, 0),
            "surgeries_op2": surgeries_op2.get(dentist.pk, 0),
            "implants": implants.get(dentist.pk, 0),
            "failed": failed.get(dentist.pk, 0),
            "required": required,
            "remaining": remaining,
            "labs": labs.get(dentist.pk, 0),
            "remakes": remakes.get(dentist.pk, 0),
            "patients": patients.get(dentist.pk, 0),
            "complaints": complaints.get(dentist.pk, 0),
            "shift_hours": round(shift_minutes[dentist.pk] / 60, 1),
            "chair_hours": round(chair[dentist.pk] / 60, 1),
            "no_shows": no_shows[dentist.pk],
            "by_type": [matrix[dentist.pk].get(type_id, 0) for type_id, _name in step_types],
        })
    rows.sort(key=lambda r: (-r["implants"], -r["steps"]))
    return render(
        request,
        "reports/dentists.html",
        {"form": form, "extra": extra, "date_from": date_from, "date_to": date_to, "rows": rows,
         "step_types": step_types},
    )


@role_required(*MANAGEMENT)
def lab_report(request):
    form, date_from, date_to, start, end = _period(request, default_days=90)
    requests = LabRequest.objects.filter(created_at__gte=start, created_at__lt=end).select_related("lab", "work_type")
    status_labels = dict(LabRequest.Status.choices)
    by_status = [
        (status_labels[row["status"]], row["status"], row["n"])
        for row in requests.values("status").annotate(n=Count("id")).order_by("status")
    ]
    by_lab = defaultdict(lambda: {"n": 0, "remakes": 0, "days": [], "cost": Decimal("0")})
    for item in requests:
        stats = by_lab[str(item.lab)]
        stats["n"] += 1
        stats["remakes"] += item.remake_count
        if item.turnaround_days is not None:
            stats["days"].append(item.turnaround_days)
        stats["cost"] += item.lab_cost or 0
    lab_rows = [
        {"lab": name, "n": s["n"], "remakes": s["remakes"], "avg_days": _avg(s["days"]), "cost": s["cost"]}
        for name, s in sorted(by_lab.items())
    ]
    overdue = LabRequest.objects.filter(status=LabRequest.Status.SENT, due_date__lt=timezone.localdate()).select_related(
        "patient", "lab", "work_type", "dentist"
    )
    return render(
        request,
        "reports/lab.html",
        {"form": form, "date_from": date_from, "date_to": date_to, "by_status": by_status,
         "lab_rows": lab_rows, "overdue": overdue, "total": requests.count()},
    )


@role_required(OWNER)
def money_report(request):
    form, date_from, date_to, _start, _end = _period(request)
    payments = Payment.objects.filter(paid_on__range=(date_from, date_to))
    method_labels = dict(PaymentMethod.choices)
    collected_by_method = [
        (method_labels[row["method"]], row["total"])
        for row in payments.values("method").annotate(total=Sum("amount")).order_by("-total")
    ]
    collected_by_course = list(
        payments.values("enrollment__course__name", "enrollment__course__code").annotate(total=Sum("amount")).order_by("-total")
    )
    outstanding = overdue = Decimal("0")
    for enrollment in Enrollment.objects.filter(status=Enrollment.Status.ACTIVE):
        outstanding += enrollment.balance
        overdue += enrollment.overdue_amount()
    line_total = ExpressionWrapper(F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=14, decimal_places=2))
    items = PurchaseItem.objects.filter(purchase__purchase_date__range=(date_from, date_to))
    rows = items.values("category").annotate(total=Sum(line_total)).order_by("-total")
    categories = PurchaseCategory.objects.in_bulk([row["category"] for row in rows])
    spent_by_category = [(categories[row["category"]], row["total"]) for row in rows]
    kind_labels = dict(PurchaseCategory.Kind.choices)
    spent_by_kind = [
        (kind_labels[row["category__kind"]], row["total"])
        for row in items.values("category__kind").annotate(total=Sum(line_total)).order_by("-total")
    ]
    spent_by_supplier = list(
        items.values("purchase__supplier__name").annotate(total=Sum(line_total)).order_by("-total")[:15]
    )
    return render(
        request,
        "reports/money.html",
        {
            "form": form, "date_from": date_from, "date_to": date_to,
            "collected": payments.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
            "collected_by_method": collected_by_method,
            "collected_by_course": collected_by_course,
            "outstanding": outstanding, "overdue": overdue,
            "spent": items.aggregate(total=Sum(line_total))["total"] or Decimal("0"),
            "spent_by_category": spent_by_category,
            "spent_by_kind": spent_by_kind,
            "spent_by_supplier": spent_by_supplier,
        },
    )


@role_required(*MANAGEMENT)
def patients_report(request):
    """Call list conversion, referral sources and complaints."""
    form, date_from, date_to, start, end = _period(request, default_days=90)
    leads = Lead.objects.filter(created_at__gte=start, created_at__lt=end)
    status_labels = dict(Lead.Status.choices)
    lead_status = [(status_labels[r["status"]], r["n"]) for r in leads.values("status").annotate(n=Count("id")).order_by("-n")]
    lead_total = leads.count()
    converted = leads.filter(status=Lead.Status.CONVERTED).count()
    patients = Patient.objects.filter(created_at__gte=start, created_at__lt=end)
    lang_en = (request.LANGUAGE_CODE or "").startswith("en")

    def source_name(row):
        if not row["referral_source"]:
            return "—"
        return row["referral_source__name_en"] if lang_en and row["referral_source__name_en"] else row["referral_source__name_ar"]

    by_source = [
        (source_name(r), r["n"])
        for r in patients.values("referral_source", "referral_source__name_ar", "referral_source__name_en")
        .annotate(n=Count("id")).order_by("-n")
    ]
    teeth_labels = dict(Patient._meta.get_field("missing_teeth").choices)
    by_teeth = [
        (teeth_labels[r["missing_teeth"]], r["n"]) for r in patients.values("missing_teeth").annotate(n=Count("id")).order_by("-n")
    ]
    top_referrers = (
        Patient.objects.annotate(n=Count("referred_patients", filter=Q(referred_patients__created_at__gte=start,
                                                                        referred_patients__created_at__lt=end)))
        .filter(n__gt=0).order_by("-n")[:10]
    )
    complaints = Complaint.objects.filter(created_at__gte=start, created_at__lt=end)
    category_labels = dict(Complaint.Category.choices)
    complaint_categories = [
        (category_labels[r["category"]], r["n"]) for r in complaints.values("category").annotate(n=Count("id")).order_by("-n")
    ]
    resolved = [c for c in complaints if c.resolved_at]
    avg_resolution_days = _avg((c.resolved_at - c.created_at).days for c in resolved)
    return render(
        request,
        "reports/patients.html",
        {
            "form": form, "date_from": date_from, "date_to": date_to,
            "lead_total": lead_total, "converted": converted, "conversion_pct": _pct(converted, lead_total),
            "lead_status": lead_status, "new_patients": patients.count(), "by_source": by_source,
            "by_teeth": by_teeth, "top_referrers": top_referrers,
            "complaint_total": complaints.count(),
            "complaint_open": complaints.filter(status__in=Complaint.OPEN_STATUSES).count(),
            "complaint_categories": complaint_categories, "avg_resolution_days": avg_resolution_days,
        },
    )
