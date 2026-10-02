"""The dashboard: every place side by side for a day, a week or a month (the owner, the head of CIA, the clinic
managers). A handful of look-ups for the whole page, whatever the size of the clinics."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .forms import DateRangeForm
from .models import Branch, ChangeRequest, PasswordHelp, switch_places
from .roles import HEAD_CIA, LAB_MONEY, MODERATOR, OWNER, has_role

VIEWERS = (OWNER, HEAD_CIA, MODERATOR)


def period(request, today):
    """(date_from, date_to, key) from ?period=today|week|month or the dates typed."""
    key = request.GET.get("period", "")
    if key == "today":
        return today, today, key
    if key == "week":
        return today - timedelta(days=6), today, key
    form = DateRangeForm(request.GET or None)
    if key != "month" and form.is_valid() and (form.cleaned_data.get("date_from") or form.cleaned_data.get("date_to")):
        date_from = form.cleaned_data.get("date_from") or today.replace(day=1)
        date_to = form.cleaned_data.get("date_to") or today
        return min(date_from, date_to), max(date_from, date_to), "dates"
    return today.replace(day=1), today, "month"


def _columns(values, days, label):
    """The bars of a chart by day: height in % of the highest, and the text of each (for the tooltip)."""
    highest = max(values.values(), default=0) or 1
    bars = []
    for day in days:
        value = values.get(day, 0)
        bars.append({"day": day, "value": value, "height": round(100 * float(value) / float(highest), 1),
                     "tip": f"{day:%a %d/%m}: {label(value)}"})
    return bars


def overview(request):
    user = request.user
    if not has_role(user, *VIEWERS):
        raise PermissionDenied
    from apps.billing.models import PatientPayment
    from apps.complaints.models import Complaint
    from apps.patients.models import Patient
    from apps.scheduling.models import Appointment, day_bounds

    today = timezone.localdate()
    date_from, date_to, key = period(request, today)
    start, end = day_bounds(date_from)[0], day_bounds(date_to)[1]
    places = switch_places(user)
    clinics = [place for place in places if place.kind != Branch.Kind.LAB]
    lab = next((place for place in places if place.kind == Branch.Kind.LAB), None)
    money = has_role(user, OWNER, MODERATOR)

    visits = {}
    for branch_id, status, n in (Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end,
                                                            branch__in=clinics)
                                 .values_list("branch", "status").annotate(n=Count("id")).order_by()):
        visits.setdefault(branch_id, {})[status] = n
    new_files = dict(Patient.objects.filter(registered_on__range=(date_from, date_to), branch__in=clinics)
                     .values("branch").annotate(n=Count("id")).values_list("branch", "n").order_by())
    paid = dict(PatientPayment.objects.filter(paid_on__range=(date_from, date_to), branch__in=clinics)
                .values("branch").annotate(t=Sum("amount")).values_list("branch", "t").order_by()) if money else {}
    complaints = dict(Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, branch__in=clinics)
                      .values("branch").annotate(n=Count("id")).values_list("branch", "n").order_by())
    done = Appointment.Status.COMPLETED
    rows = []
    for place in clinics:
        counts = visits.get(place.pk, {})
        booked = sum(n for status, n in counts.items() if status != Appointment.Status.CANCELLED)
        missed = counts.get(Appointment.Status.NO_SHOW, 0)
        rows.append({"place": place, "booked": booked, "done": counts.get(done, 0), "missed": missed,
                     "missed_rate": round(100 * missed / booked) if booked else None,
                     "new_files": new_files.get(place.pk, 0), "paid": paid.get(place.pk) or Decimal("0"),
                     "complaints": complaints.get(place.pk, 0)})
    top_done = max((row["done"] for row in rows), default=0) or 1
    top_paid = max((row["paid"] for row in rows), default=0) or 1
    for row in rows:
        row["done_width"] = round(100 * row["done"] / top_done)
        row["paid_width"] = round(100 * float(row["paid"]) / float(top_paid))
    totals = {name: sum((row[name] for row in rows), 0) for name in ("booked", "done", "missed", "new_files",
                                                                      "complaints")}
    totals["paid"] = sum((row["paid"] for row in rows), Decimal("0"))

    days = [date_from + timedelta(days=n) for n in range((date_to - date_from).days + 1)]
    charts = []
    if 1 < len(days) <= 62:  # a column for each day (a longer period: the table of the places only)
        per_day = dict(Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end, branch__in=clinics,
                                                  status=done)
                       .annotate(day=TruncDate("scheduled_at", tzinfo=timezone.get_current_timezone()))
                       .values("day").annotate(n=Count("id")).values_list("day", "n").order_by())
        charts.append({"title": _("Visits finished, each day"), "icon": "bi-calendar-check", "first": days[0],
                       "last": days[-1],
                       "bars": _columns(per_day, days, lambda v: _("%(n)s visits") % {"n": v}),
                       "total": sum(per_day.values()), "money": False})
        if money:
            per_day = dict(PatientPayment.objects.filter(paid_on__range=(date_from, date_to), branch__in=clinics)
                           .values("paid_on").annotate(t=Sum("amount")).values_list("paid_on", "t").order_by())
            charts.append({"title": _("Money received from the patients, each day"), "icon": "bi-cash-stack",
                           "first": days[0], "last": days[-1],
                           "bars": _columns(per_day, days, lambda v: f"{v:,.0f}"),
                           "total": sum(per_day.values(), Decimal("0")), "money": True})

    context = {"date_from": date_from, "date_to": date_to, "key": key, "rows": rows, "totals": totals,
               "money": money, "charts": charts, "form": DateRangeForm(initial={"date_from": date_from,
                                                                               "date_to": date_to}),
               "attention": attention(user, clinics, today)}
    if lab is not None:
        context["lab"] = lab_part(user, date_from, date_to)
    return render(request, "core/overview.html", context)


def lab_part(user, date_from, date_to):
    from django.db.models import Q

    from apps.lab.models import CLOSED_STEPS, LabCase, LabPayment, Step
    from apps.lab.stats import board_counts, bounds

    start, end = bounds(date_from, date_to)
    counts = board_counts()
    groups = [(_("On the way"), [Step.INCOMING]), (_("To give out"), [Step.RECEIVED]),
              (_("Design"), [Step.MODELS, Step.DESIGN, Step.DESIGN_CHECK]),
              (_("Milling, printing, casting"), [Step.MILLING, Step.PRINTING, Step.METAL_PRINTING, Step.CASTING,
                                                 Step.SINTERING]),
              (_("Finishing"), [Step.CERAMIC, Step.STAIN_GLAZE, Step.SETUP, Step.PROCESSING, Step.FINISHING]),
              (_("Quality check"), [Step.QC]), (_("Ready"), [Step.READY]),
              (_("At the clinic, another lab, on hold"), [Step.TRY_IN, Step.OUTSOURCED, Step.ON_HOLD])]
    steps = [{"label": label, "n": sum(counts.get(code, 0) for code in codes)} for label, codes in groups]
    top = max((row["n"] for row in steps), default=0) or 1
    for row in steps:
        row["width"] = round(100 * row["n"] / top)
    cases = LabCase.objects.all()
    part = {
        "steps": steps, "open": sum(row["n"] for row in steps),
        "received": cases.filter(received_at__gte=start, received_at__lt=end).count(),
        "delivered": cases.filter(step=Step.DELIVERED, delivered_at__gte=start, delivered_at__lt=end).count(),
        "late": cases.exclude(step__in=CLOSED_STEPS).filter(due_date__lt=timezone.localdate()).count(),
        "remakes": cases.filter(Q(remake_of__isnull=False), created_at__gte=start, created_at__lt=end).count(),
    }
    if has_role(user, *LAB_MONEY):
        part["billed"] = cases.filter(step=Step.DELIVERED, delivered_at__gte=start,
                                      delivered_at__lt=end).aggregate(t=Sum("total"))["t"] or 0
        part["paid"] = LabPayment.objects.filter(cancelled_at__isnull=True, paid_on__range=(date_from, date_to)) \
            .aggregate(t=Sum("amount"))["t"] or 0
    return part


def attention(user, clinics, today):
    """What waits for someone now: approvals, late lab work, complaints past their date, stock running low."""
    from apps.clinical.models import LabRequest
    from apps.complaints.models import Complaint
    from apps.stock.views import low_stock

    from .approvals import changes_for

    items = []
    approvals = changes_for(user).filter(status=ChangeRequest.Status.PENDING).count()
    if approvals:
        items.append(("bi-check2-square", _("Changes waiting for your approval"), approvals, reverse("core:approvals")))
    late_lab = LabRequest.objects.filter(status=LabRequest.Status.SENT, due_date__lt=today,
                                         branch__in=clinics).count()
    if late_lab:
        items.append(("bi-lab-request", _("Lab work late (past the date it was needed)"), late_lab,
                      reverse("clinical:lab_list") + "?overdue=1"))
    overdue = Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, follow_up_due__lt=today,
                                       branch__in=clinics).count()
    if overdue:
        items.append(("bi-chat-left-dots", _("Complaints past their follow-up date"), overdue, reverse("complaints:list")))
    if has_role(user, OWNER, HEAD_CIA):
        low = low_stock().count()
        if low:
            items.append(("bi-boxes", _("Stock items running low"), low, reverse("stock:item_list") + "?low=on"))
    if has_role(user, OWNER):
        asked = PasswordHelp.objects.filter(status=PasswordHelp.Status.NEW).count()
        if asked:
            items.append(("bi-key", _("Forgotten passwords to answer"), asked, reverse("settings:users")))
    return items


def places_now(user, today):
    """The owner's home page (round 13): every place side by side, the same size and in the same order (CIA, El
    Khadem, CIC, the lab), whatever place is chosen in the switch: today's visits, this month's new files and money,
    the open complaints; for the lab its cases."""
    from apps.billing.models import PatientPayment
    from apps.complaints.models import Complaint
    from apps.patients.models import Patient
    from apps.scheduling.models import Appointment, day_bounds

    places = sorted(switch_places(user), key=lambda place: (place.kind == Branch.Kind.LAB, place.sort_order, place.pk))
    clinics = [place for place in places if place.kind != Branch.Kind.LAB]
    start, end = day_bounds(today)
    month = today.replace(day=1)
    money = has_role(user, OWNER, MODERATOR)
    visits = {}
    for branch_id, status, n in (Appointment.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end,
                                                            branch__in=clinics)
                                 .values_list("branch", "status").annotate(n=Count("id")).order_by()):
        visits.setdefault(branch_id, {})[status] = n
    new_files = dict(Patient.objects.filter(registered_on__gte=month, branch__in=clinics)
                     .values("branch").annotate(n=Count("id")).values_list("branch", "n").order_by())
    complaints = dict(Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES, branch__in=clinics)
                      .values("branch").annotate(n=Count("id")).values_list("branch", "n").order_by())
    paid_today = paid_month = {}
    if money:
        payments = PatientPayment.objects.filter(branch__in=clinics)
        paid_today = dict(payments.filter(paid_on=today).values("branch").annotate(t=Sum("amount"))
                          .values_list("branch", "t").order_by())
        paid_month = dict(payments.filter(paid_on__gte=month).values("branch").annotate(t=Sum("amount"))
                          .values_list("branch", "t").order_by())
    S = Appointment.Status
    cards = []
    for place in places:
        if place.kind == Branch.Kind.LAB:
            cards.append({"place": place, "lab": True, "stats": lab_now(user, today)})
            continue
        counts = visits.get(place.pk, {})
        stats = [
            (_("booked today"), sum(n for status, n in counts.items() if status != S.CANCELLED), ""),
            (_("here now"), counts.get(S.ARRIVED, 0) + counts.get(S.IN_ROOM, 0), "text-primary"),
            (_("finished"), counts.get(S.COMPLETED, 0), "text-success"),
            (_("new files this month"), new_files.get(place.pk, 0), ""),
        ]
        if money:
            stats += [(_("paid today"), paid_today.get(place.pk) or Decimal("0"), "money"),
                      (_("paid this month"), paid_month.get(place.pk) or Decimal("0"), "money")]
        stats.append((_("open complaints"), complaints.get(place.pk, 0), "text-danger" if complaints.get(place.pk) else ""))
        cards.append({"place": place, "lab": False, "stats": stats})
    return cards


def lab_now(user, today):
    """The lab's numbers for the owner's home page: cases in the lab, late, received and delivered today."""
    from apps.lab.models import CLOSED_STEPS, LabCase, LabPayment, Step
    from apps.lab.stats import bounds

    start, end = bounds(today, today)
    cases = LabCase.objects.all()
    stats = [
        (_("cases in the lab"), cases.exclude(step__in=CLOSED_STEPS).count(), ""),
        (_("late"), cases.exclude(step__in=CLOSED_STEPS).filter(due_date__lt=today).count(), "text-danger"),
        (_("received today"), cases.filter(received_at__gte=start, received_at__lt=end).count(), ""),
        (_("delivered today"), cases.filter(step=Step.DELIVERED, delivered_at__gte=start, delivered_at__lt=end).count(),
         "text-success"),
    ]
    if has_role(user, *LAB_MONEY):
        stats.append((_("paid this month"), LabPayment.objects.filter(
            cancelled_at__isnull=True, paid_on__gte=today.replace(day=1)).aggregate(t=Sum("amount"))["t"]
            or Decimal("0"), "money"))
    return stats
