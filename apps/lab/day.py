"""The end of the day at the lab (round 14): the lab's receipts of the day, added up by payment method and by who
received them, the work delivered that day, the cash counted in the drawer and the owner's review. Before, the "End
of the day" page opened at the lab showed CIA's day.

A day closed here is a ``billing.DayClosing`` of the lab's place, like a clinic's."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.academy.models import PaymentMethod
from apps.billing.forms import DayCloseForm, DayReviewForm
from apps.billing.models import DayClosing
from apps.core.forms import StyledForm
from apps.core.mixins import role_required
from apps.core.models import Branch
from apps.core.roles import LAB_DESK, LAB_MONEY, has_role

from .models import LabCase, LabPayment, Step
from .stats import bounds

ZERO = Decimal("0")


def lab_place():
    return Branch.objects.filter(kind=Branch.Kind.LAB, is_active=True).order_by("sort_order", "pk").first()


class LabDayForm(StyledForm):
    day = forms.DateField(label=gettext_lazy("day"), required=False)


def day_summary(day):
    """The lab's receipts of a day (cancelled ones crossed out) and the work delivered that day."""
    receipts = list(LabPayment.objects.filter(paid_on=day).select_related("client", "received_by", "cancelled_by")
                    .order_by("pk"))
    live = [p for p in receipts if not p.is_cancelled]
    labels = dict(PaymentMethod.choices)
    by_method, by_person = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for payment in live:
        by_method[payment.method] += payment.amount
        by_person[payment.received_by] += payment.amount
    start, end = bounds(day, day)
    delivered = list(LabCase.objects.filter(step=Step.DELIVERED, delivered_at__gte=start, delivered_at__lt=end)
                     .select_related("client").order_by("delivered_at"))
    return {
        "receipts": receipts,
        "by_method": sorted(((labels.get(k, k), v, k) for k, v in by_method.items()), key=lambda row: -row[1]),
        "by_person": sorted(by_person.items(), key=lambda row: -row[1]),
        "total": sum((p.amount for p in live), ZERO),
        "cash": by_method.get(PaymentMethod.CASH, ZERO),
        "count": len(live),
        "cancelled": [p for p in receipts if p.is_cancelled],
        "delivered": delivered,
        "delivered_value": sum((case.total or ZERO for case in delivered), ZERO),
    }


@role_required(*LAB_DESK)
def lab_day(request):
    today = timezone.localdate()
    place = lab_place()
    form = LabDayForm(request.GET or None, initial={"day": today})
    day = (form.cleaned_data.get("day") if form.is_valid() else None) or today
    summary = day_summary(day)
    closing = DayClosing.objects.filter(branch=place, day=day).select_related("closed_by", "reviewed_by").first()
    reviewer = has_role(request.user, *LAB_MONEY)
    close_form = DayCloseForm(request.POST if request.POST.get("action") == "close" else None)
    review_form = DayReviewForm(request.POST if request.POST.get("action") == "review" else None)
    if request.method == "POST" and place is not None:
        action = request.POST.get("action")
        if action == "close" and closing is None and close_form.is_valid():
            DayClosing.objects.create(
                branch=place, day=day, totals={row[2]: str(row[1]) for row in summary["by_method"]},
                total=summary["total"], receipts=summary["count"], cash_expected=summary["cash"],
                cash_counted=close_form.cleaned_data["cash_counted"], notes=close_form.cleaned_data.get("notes", ""),
                closed_by=request.user)
            messages.success(request, _("The day is closed. The owner can now review it."))
            return redirect(request.get_full_path())
        if action == "review" and closing is not None and reviewer and review_form.is_valid():
            closing.reviewed_by, closing.reviewed_at = request.user, timezone.now()
            closing.review_notes = review_form.cleaned_data.get("review_notes", "")
            closing.save()
            messages.success(request, _("Marked as reviewed."))
            return redirect(request.get_full_path())
    return render(request, "lab/day.html", {
        "form": form, "day": day, "place": place, "summary": summary, "closing": closing, "reviewer": reviewer,
        "close_form": close_form, "review_form": review_form, "is_today": day == today,
    })


@role_required(*LAB_DESK)
def lab_month(request):
    """Each day of a month at the lab: what was received, whether the day was closed and reviewed."""
    today = timezone.localdate()
    place = lab_place()
    try:
        first = datetime.strptime(request.GET.get("month", ""), "%Y-%m").date()
    except ValueError:
        first = today.replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    totals = {row["paid_on"]: row for row in LabPayment.objects.filter(
        cancelled_at__isnull=True, paid_on__range=(first, last)).values("paid_on").annotate(
        total=Sum("amount"), n=Count("id")).order_by()}
    closings = {c.day: c for c in DayClosing.objects.filter(branch=place, day__range=(first, last))}
    rows, day = [], first
    while day <= min(last, today):
        if day in totals or day in closings:
            rows.append({"day": day, "total": totals.get(day, {}).get("total") or ZERO,
                         "count": totals.get(day, {}).get("n") or 0, "closing": closings.get(day)})
        day += timedelta(days=1)
    return render(request, "billing/month_review.html", {
        "rows": rows, "first": first, "place": place, "places": [place], "day_url": "lab:day", "lab": True,
        "total": sum((r["total"] for r in rows), ZERO),
        "prev_month": (first - timedelta(days=1)).replace(day=1), "next_month": last + timedelta(days=1),
    })
