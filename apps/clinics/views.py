from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.academy.models import PaymentMethod
from apps.billing.models import Charge, PatientPayment
from apps.core.mixins import role_required
from apps.core.models import Branch, branch_for_user, working_places
from apps.core.utils import minutes_between
from apps.core.roles import CLINIC_MANAGERS, has_role
from apps.dentists.models import Dentist
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from .forms import FeeRuleForm, PayoutForm, PlacePeriodForm
from .models import DoctorPayout, FeeRule
from .shares import ZERO, _bounds, owed, statement, summary


def _default_place(user, places):
    """The place worked in when it pays its doctors by rules; else the first place that does."""
    here = branch_for_user(user)
    with_rules = set(FeeRule.objects.values_list("branch_id", flat=True))
    if here in places and here.pk in with_rules:
        return here
    return next((p for p in places if p.pk in with_rules), here if here in places else (places[0] if places else None))


def _filters(request, places):
    """The place and the period chosen on the page (this month by default)."""
    today = timezone.localdate()
    form = PlacePeriodForm(request.GET or None, places=places)
    data = form.cleaned_data if form.is_valid() else {}
    place = next((p for p in places if p.code == data.get("place")), None) or _default_place(request.user, places)
    date_from = data.get("date_from") or today.replace(day=1)
    date_to = data.get("date_to") or today
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    if not form.is_bound:
        form = PlacePeriodForm(places=places, initial={"place": place.code if place else "", "date_from": date_from,
                                                        "date_to": date_to})
    return form, place, date_from, date_to


def _query(place, date_from, date_to):
    return f"?place={place.code}&date_from={date_from:%d/%m/%Y}&date_to={date_to:%d/%m/%Y}"


@role_required(*CLINIC_MANAGERS)
def doctors(request):
    """Each doctor of a place: visits, time in the chair, what was billed and paid, their share and what is owed."""
    places = list(working_places(request.user))
    form, place, date_from, date_to = _filters(request, places)
    rows, totals = summary(place, date_from, date_to) if place else ([], {})
    return render(request, "clinics/doctors.html", {
        "form": form, "place": place, "date_from": date_from, "date_to": date_to, "rows": rows, "totals": totals,
        "query": _query(place, date_from, date_to) if place else "",
    })


def statement_view(request, pk):
    """One doctor's statement at a place. The doctor can open their own; the managers record payments here."""
    dentist = get_object_or_404(Dentist, pk=pk)
    manager = has_role(request.user, *CLINIC_MANAGERS)
    me = Dentist.for_user(request.user)
    if not manager and (me is None or me.pk != dentist.pk):
        raise PermissionDenied
    if manager:
        places = list(working_places(request.user))
    else:
        ids = set(dentist.fee_rules.values_list("branch_id", flat=True)) | set(dentist.places.values_list("pk", flat=True))
        places = list(Branch.objects.filter(pk__in=ids).order_by("sort_order", "pk"))
    if not places:
        raise PermissionDenied
    form, place, date_from, date_to = _filters(request, places)
    payout_form = PayoutForm(request.POST if manager and request.method == "POST" else None,
                             initial={"period_from": date_from, "period_to": date_to})
    if manager and request.method == "POST" and payout_form.is_valid():
        payout = payout_form.save(commit=False)
        payout.dentist, payout.branch, payout.created_by = dentist, place, request.user
        payout.save()
        messages.success(request, _("Payment of %(amount)s to %(doctor)s saved.")
                         % {"amount": f"{payout.amount:,.2f}", "doctor": dentist})
        return redirect(reverse("clinics:statement", args=[dentist.pk]) + _query(place, date_from, date_to))
    data = statement(dentist, place, date_from, date_to)
    return render(request, "clinics/statement.html", {
        **data, "form": form, "place": place, "owed": owed(dentist, place, date_to), "manager": manager,
        "payout_form": payout_form if manager else None, "query": _query(place, date_from, date_to),
    })


def my_shares(request):
    """The logged-in doctor's own statement."""
    me = Dentist.for_user(request.user)
    if me is None:
        raise PermissionDenied
    return redirect("clinics:statement", pk=me.pk)


@role_required(*CLINIC_MANAGERS)
def rules(request):
    places = list(working_places(request.user))
    form, place, _date_from, _date_to = _filters(request, places)
    by_doctor = defaultdict(list)
    for rule in FeeRule.objects.filter(branch=place).select_related("dentist", "service").order_by(
            "dentist__full_name", "service__name_ar", "-starts_on"):
        by_doctor[rule.dentist].append(rule)
    without = Dentist.objects.active().working_at(place).exclude(pk__in=[d.pk for d in by_doctor]).order_by("full_name") \
        if place else Dentist.objects.none()
    return render(request, "clinics/rules.html", {
        "form": form, "place": place, "by_doctor": sorted(by_doctor.items(), key=lambda item: item[0].full_name),
        "without_rules": without,
    })


@role_required(*CLINIC_MANAGERS)
def rule_edit(request, pk=None):
    places = list(working_places(request.user))
    rule = get_object_or_404(FeeRule, pk=pk, branch__in=places) if pk else None
    place = rule.branch if rule else next((p for p in places if p.code == request.GET.get("place")), None) \
        or _default_place(request.user, places)
    initial = {}
    if rule is None and request.GET.get("dentist", "").isdigit():
        initial["dentist"] = int(request.GET["dentist"])
    form = FeeRuleForm(request.POST or None, instance=rule, places=places, place=place, initial=initial)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if saved.pk is None:
            saved.created_by = request.user
        saved.branch = place
        saved.save()
        messages.success(request, _("Saved: %(rule)s.") % {"rule": saved})
        return redirect(reverse("clinics:rules") + f"?place={place.code}")
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Doctor's fee rule") + f" — {place.code}", "title_icon": "bi-percent",
        "cancel_url": reverse("clinics:rules") + f"?place={place.code}",
        "intro": _("A rule for one service (e.g. implants) comes before the rule for every service. To change a "
                   "doctor's percentage from a date, add a new rule from that date: the old services keep the old "
                   "rule."),
    })


@role_required(*CLINIC_MANAGERS)
@require_POST
def payout_delete(request, pk):
    payout = get_object_or_404(DoctorPayout, pk=pk, branch__in=list(working_places(request.user)))
    target = reverse("clinics:statement", args=[payout.dentist_id]) + f"?place={payout.branch.code}"
    payout.delete()
    messages.success(request, _("Payment deleted."))
    return redirect(target)


@role_required(*CLINIC_MANAGERS)
def report(request):
    """A place over a period: money in, visits and time, the doctors' shares, materials used, and what is left."""
    from apps.stock.models import StockMovement

    places = list(working_places(request.user))
    form, place, date_from, date_to = _filters(request, places)
    start, end = _bounds(date_from, date_to)
    payments = PatientPayment.objects.filter(branch=place, paid_on__range=(date_from, date_to))
    collected = payments.aggregate(total=Sum("amount"))["total"] or ZERO
    methods = dict(PaymentMethod.choices)
    by_method = sorted(((methods.get(r["method"], r["method"]), r["total"])
                        for r in payments.values("method").annotate(total=Sum("amount"))), key=lambda r: -r[1])
    by_machine = [(r["fawry_machine__name"] or "—", r["total"]) for r in
                  payments.filter(method=PaymentMethod.FAWRY).values("fawry_machine__name").annotate(total=Sum("amount"))
                  .order_by("fawry_machine__name")]
    billed = sum((price - (price * percent / 100).quantize(Decimal("0.01")) for price, percent in
                  Charge.objects.filter(branch=place, charged_on__range=(date_from, date_to)).order_by()
                  .values_list("price", "discount_percent")), ZERO)
    appointments = Appointment.objects.filter(branch=place, scheduled_at__gte=start, scheduled_at__lt=end)
    done = list(appointments.filter(status=Appointment.Status.COMPLETED).order_by()
                .values_list("patient_id", "scheduled_at", "entered_room_at", "left_at"))
    status_labels = dict(Appointment.Status.choices)
    by_status = [(status_labels[r["status"]], r["n"]) for r in
                 appointments.values("status").annotate(n=Count("id")).order_by("status")]
    chair_minutes = sum(minutes_between(row[2], row[3]) or 0 for row in done)
    rows, totals = summary(place, date_from, date_to)
    used = StockMovement.objects.filter(branch=place, kind__in=(StockMovement.Kind.OUT, StockMovement.Kind.WASTE),
                                        moved_at__gte=start, moved_at__lt=end).select_related("item")
    stock_used = sum((m.quantity * (m.unit_cost or m.item.unit_cost or ZERO) for m in used), ZERO)
    share = totals.get("share", ZERO)

    days = []
    if (date_to - date_from).days <= 62:
        visits_by_day = defaultdict(int)
        for row in done:
            visits_by_day[timezone.localtime(row[1]).date()] += 1
        money_by_day = {r["paid_on"]: r["total"] for r in payments.values("paid_on").annotate(total=Sum("amount"))}
        top_money = max(money_by_day.values(), default=ZERO) or Decimal("1")
        top_visits = max(visits_by_day.values(), default=0) or 1
        day = date_from
        while day <= date_to:
            money, visits = money_by_day.get(day, ZERO), visits_by_day.get(day, 0)
            if money or visits:
                days.append({"day": day, "money": money, "visits": visits,
                             "money_pct": int(money * 100 / top_money), "visits_pct": int(visits * 100 / top_visits)})
            day += timedelta(days=1)
    return render(request, "clinics/report.html", {
        "form": form, "place": place, "date_from": date_from, "date_to": date_to, "query": _query(place, date_from, date_to),
        "collected": collected, "billed": billed, "by_method": by_method, "by_machine": by_machine,
        "visit_count": len(done), "by_status": by_status, "chair_minutes": chair_minutes,
        "patients_seen": len({row[0] for row in done}),
        "new_files": Patient.objects.filter(branch=place, created_at__gte=start, created_at__lt=end).count(),
        "rows": rows, "totals": totals, "stock_used": stock_used, "left": collected - share - stock_used,
        "days": days,
    })
