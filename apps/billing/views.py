from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.academy.models import PaymentMethod
from apps.core.mixins import role_required
from apps.core.models import Branch, ClinicSettings, Notification, branch_for_user, staff_at, working_places
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import CLINICAL, FRONT_DESK, HEAD_CIA, OWNER, SECRETARY, has_role
from apps.core.utils import normalize_digits
from apps.dentists.models import Dentist
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from . import fawry, receipts
from .forms import (
    BillFilterForm,
    BillForm,
    BillLineFormSet,
    ChargeForm,
    DayCloseForm,
    DayPickForm,
    DayReviewForm,
    FawryFilterForm,
    FawryMoveForm,
    FawryPercentForm,
    PatientPaymentForm,
    PaymentFilterForm,
    PayNowForm,
    ReceiptCancelForm,
    ReceiptCorrectForm,
    OwnerCashForm,
    RefundForm,
    ServiceRefundForm,
    chosen_places,
)
from .models import (
    Bill, DayClosing, FawryMachine, FawryMove, PatientPayment, Service, account, bill_totals, create_bill, paid_services,
)


PER_PAGE = 200  # rows on one page of a long list; the totals are for the whole period


@role_required(*FRONT_DESK)
def patient_account(request, pk):
    """The patient's services (price, discount, paid, left) and payments, with forms to add both."""
    patient = get_object_or_404(Patient, pk=pk)
    here = branch_for_user(request.user)
    current = account(patient)
    action = request.POST.get("action")
    charge_form = ChargeForm(request.POST if action == "charge" else None, prefix="c", branch=here,
                             initial={"charged_on": timezone.localdate()})
    payment_form = PatientPaymentForm(request.POST if action == "payment" else None, prefix="p", account=current,
                                      initial={"paid_on": timezone.localdate()})
    if action == "charge" and charge_form.is_valid():
        charge = charge_form.save(commit=False)
        charge.patient, charge.created_by, charge.branch = patient, request.user, here
        charge.save()
        messages.success(request, _("%(service)s added: %(net)s to pay.") % {"service": charge.service,
                                                                            "net": f"{charge.net:,.2f}"})
        return redirect("billing:account", pk=patient.pk)
    if action == "payment" and payment_form.is_valid():
        with transaction.atomic():
            payment = payment_form.save(commit=False)
            payment.patient, payment.created_by = patient, request.user
            payment.branch = payment.charge.branch if payment.charge_id else here
            payment.save()
        messages.success(request, _("Payment saved. Receipt %(number)s.") % {"number": payment.receipt_number})
        return redirect(payment)
    return render(request, "billing/account.html", {
        "patient": patient, "account": current, "charge_form": charge_form, "payment_form": payment_form,
    })


@role_required(*FRONT_DESK)
def receipt(request, pk):
    """The receipt (80 mm, for the receipt printer), with its changes and what can be done with it."""
    from apps.core.signatures import person_signature

    payment = get_object_or_404(PatientPayment.every.select_related(
        "patient", "charge__service", "created_by__profile", "branch", "fawry_machine", "refund_of", "cancelled_by",
        "bill__dentist__user__profile"), pk=pk)
    services = paid_services(payment)
    # The doctor who signs: the one of the bill, else of the (first) service paid.
    doctor = payment.bill.dentist if payment.bill_id and payment.bill.dentist_id else next(
        (charge.dentist for charge, _amount in services if charge.dentist_id), None)
    return render(request, "billing/receipt.html", {
        "payment": payment, "account": account(payment.patient), "can_change": receipts.can_change(request.user, payment),
        "log": payment.log.select_related("done_by"), "refunds": PatientPayment.every.filter(refund_of=payment),
        "services": services,
        "signatures": [(_("Received by"), *person_signature(payment.created_by)),
                       (_("Doctor"), str(doctor) if doctor else "", doctor.signature_image if doctor else "")],
    })


@role_required(*FRONT_DESK)
def refund_page(request, pk):
    """Give money back by tapping what is given back (round 15): each service the patient paid, with the receipts
    that paid it (they open beside it, to show the patient); the amount fills in by itself."""
    patient = get_object_or_404(Patient.objects.here(), pk=pk)
    rows = [row for row in receipts.service_receipts(patient).values() if row["paid"] > 0]
    form = ServiceRefundForm(request.POST or None)
    chosen = {}
    if request.method == "POST":
        for row in rows:
            pk_ = row["charge"].pk
            if request.POST.get(f"take_{pk_}"):
                try:
                    chosen[pk_] = Decimal(normalize_digits(request.POST.get(f"amount_{pk_}") or "0"))
                except InvalidOperation:
                    chosen[pk_] = Decimal("0")
        if not chosen:
            messages.error(request, _("Tap the services given back."))
        elif form.is_valid():
            data = form.cleaned_data
            try:
                backs = receipts.refund_services(patient, request.user, list(chosen.items()), data["method"],
                                                 data["reason"], data.get("fawry_machine"), data["not_done"])
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                total = -sum((back.amount for back in backs), Decimal("0"))
                messages.success(request, _("%(amount)s given back: receipt %(numbers)s.") % {
                    "amount": f"{total:,.2f}", "numbers": ", ".join(back.receipt_number for back in backs)})
                return redirect(backs[0]) if len(backs) == 1 else redirect("billing:account", pk=patient.pk)
    for row in rows:
        row["chosen"] = row["charge"].pk in chosen
        row["amount"] = chosen.get(row["charge"].pk, row["paid"])
    return render(request, "billing/refund.html", {"patient": patient, "rows": rows, "form": form})


@role_required(*FRONT_DESK)
def receipt_change(request, pk):
    """Correct, cancel or refund a receipt, with the reason (see receipts.py)."""
    payment = get_object_or_404(PatientPayment.every.select_related("patient"), pk=pk)
    action = request.POST.get("action")
    initial = {"amount": payment.amount, "method": payment.method, "fawry_machine": payment.fawry_machine,
               "reference": payment.reference}
    correct_form = ReceiptCorrectForm(request.POST if action == "correct" else None, initial=initial, prefix="c")
    cancel_form = ReceiptCancelForm(request.POST if action == "cancel" else None, prefix="x")
    refund_form = RefundForm(request.POST if action == "refund" else None, prefix="r",
                             initial={"amount": max(payment.refundable(), Decimal("0"))})
    if request.method == "POST":
        try:
            if action == "correct" and correct_form.is_valid():
                data = correct_form.cleaned_data
                receipts.correct(payment, request.user, data["reason"], amount=data["amount"], method=data["method"],
                                 fawry_machine=data.get("fawry_machine"), reference=data.get("reference", ""))
                messages.success(request, _("Receipt %(number)s corrected.") % {"number": payment.receipt_number})
                return redirect(payment)
            if action == "cancel" and cancel_form.is_valid():
                receipts.cancel(payment, request.user, cancel_form.cleaned_data["reason"])
                messages.success(request, _("Receipt %(number)s cancelled. It stays in the day's list, crossed out.")
                                 % {"number": payment.receipt_number})
                return redirect(payment)
            if action == "refund" and refund_form.is_valid():
                data = refund_form.cleaned_data
                back = receipts.refund(payment, request.user, data["amount"], data["method"], data["reason"],
                                       data.get("fawry_machine"))
                messages.success(request, _("Refund saved: receipt %(number)s.") % {"number": back.receipt_number})
                return redirect(back)
        except ValidationError as error:
            messages.error(request, error.messages[0])
    return render(request, "billing/receipt_change.html", {
        "payment": payment, "can_change": receipts.can_change(request.user, payment),
        "correct_form": correct_form, "cancel_form": cancel_form, "refund_form": refund_form,
    })


@role_required(*FRONT_DESK)
def day_review(request):
    """The end of the day at a place: every receipt (cancelled ones crossed out), the totals by payment method,
    the bills, the changes; the reception closes the day with the cash counted, the owner marks it reviewed."""
    today = timezone.localdate()
    here, places = branch_for_user(request.user), list(working_places(request.user))
    if here is not None and here.kind == Branch.Kind.LAB:  # the lab's day is its own receipts (round 14)
        return redirect(reverse("lab:day") + (f"?{request.GET.urlencode()}" if request.GET else ""))
    form = DayPickForm(request.GET or None, places=places, current=here, initial={"day": today})
    data = form.cleaned_data if form.is_valid() else {}
    day = data.get("day") or today
    shown = chosen_places(form, places, here)
    place = shown[0] if len(shown) == 1 else None
    summary = receipts.day_summary(place, day) if place is not None else None
    closing = DayClosing.objects.filter(branch=place, day=day).select_related("closed_by", "reviewed_by").first() \
        if place is not None else None
    reviewer = has_role(request.user, OWNER, HEAD_CIA)
    close_form = DayCloseForm(request.POST if request.POST.get("action") == "close" else None)
    review_form = DayReviewForm(request.POST if request.POST.get("action") == "review" else None)
    if request.method == "POST" and place is not None:
        action = request.POST.get("action")
        if action == "close" and closing is None and close_form.is_valid():
            DayClosing.objects.create(
                branch=place, day=day, totals={row[2]: str(row[1]) for row in summary["by_method"]},
                total=summary["total"], receipts=summary["count"], cash_expected=summary["drawer"],
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
    return render(request, "billing/day_review.html", {
        "form": form, "day": day, "place": place, "summary": summary, "closing": closing, "reviewer": reviewer,
        "close_form": close_form, "review_form": review_form, "is_today": day == today,
    })


@role_required(*FRONT_DESK)
def owner_cash(request):
    """Money the owner puts in at a place when the spending is more than what came in, or takes out (round 15):
    the cash counts in the day's drawer and every move in the balance sheet. The owner is told when the reception
    writes one."""
    from .models import OwnerCash

    here, places = branch_for_user(request.user), list(working_places(request.user))
    code = request.GET.get("place") or request.POST.get("place")
    place = next((p for p in places if p.code == code), here)
    form = OwnerCashForm(request.POST or None, initial={"moved_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        move = form.save(commit=False)
        move.branch, move.created_by = place, request.user
        move.save()
        if not has_role(request.user, OWNER):
            notify_roles((OWNER,), gettext_lazy("The owner's money at %(place)s: %(what)s %(amount)s"), "%(reason)s",
                         reverse("billing:owner_cash") + f"?place={place.code}", exclude=request.user,
                         params={"place": place.code, "what": move.get_direction_display(),
                                 "amount": f"{move.amount:,.2f}", "reason": move.reason})
        messages.success(request, _("Saved: %(what)s %(amount)s.") % {"what": move.get_direction_display(),
                                                                      "amount": f"{move.amount:,.2f}"})
        return redirect(f"{reverse('billing:owner_cash')}?place={place.code}")
    moves = list(OwnerCash.objects.filter(branch=place).select_related("created_by")[:100])
    month = timezone.localdate().replace(day=1)
    this_month = [m for m in moves if m.moved_on >= month]
    return render(request, "billing/owner_cash.html", {
        "form": form, "place": place, "places": places, "moves": moves,
        "month_in": sum((m.amount for m in this_month if m.direction == "in"), Decimal("0")),
        "month_out": sum((m.amount for m in this_month if m.direction == "out"), Decimal("0")),
    })


@role_required(*FRONT_DESK)
def month_review(request):
    """Each day of a month at a place: what was received, whether the day was closed and reviewed."""
    today = timezone.localdate()
    here, places = branch_for_user(request.user), list(working_places(request.user))
    if here is not None and here.kind == Branch.Kind.LAB:
        return redirect(reverse("lab:month") + (f"?{request.GET.urlencode()}" if request.GET else ""))
    try:
        first = datetime.strptime(request.GET.get("month", ""), "%Y-%m").date()
    except ValueError:
        first = today.replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    code = request.GET.get("place")
    place = next((p for p in places if p.code == code), here)
    rows = []
    totals = {row["paid_on"]: row for row in PatientPayment.objects.filter(
        branch=place, paid_on__range=(first, last)).values("paid_on").annotate(total=Sum("amount"), n=Count("id"))}
    closings = {c.day: c for c in DayClosing.objects.filter(branch=place, day__range=(first, last))}
    day = first
    while day <= min(last, today):
        if day in totals or day in closings:
            rows.append({"day": day, "total": totals.get(day, {}).get("total") or Decimal("0"),
                         "count": totals.get(day, {}).get("n") or 0, "closing": closings.get(day)})
        day += timedelta(days=1)
    return render(request, "billing/month_review.html", {
        "rows": rows, "first": first, "place": place, "places": places,
        "total": sum((r["total"] for r in rows), Decimal("0")),
        "prev_month": (first - timedelta(days=1)).replace(day=1), "next_month": last + timedelta(days=1),
    })


@role_required(*FRONT_DESK)
def payment_list(request):
    """What the reception collected: by day, with the total for each payment method."""
    today = timezone.localdate()
    here, places = branch_for_user(request.user), list(working_places(request.user))
    form = PaymentFilterForm(request.GET or None, places=places, current=here)
    data = form.cleaned_data if form.is_valid() else {}
    date_from, date_to = data.get("date_from") or today, data.get("date_to") or today
    shown = chosen_places(form, places, here)
    payments = PatientPayment.objects.filter(paid_on__range=(date_from, date_to), branch__in=shown).select_related(
        "patient", "charge__service", "created_by", "branch", "fawry_machine")
    if data.get("method"):
        payments = payments.filter(method=data["method"])
    labels = dict(PaymentMethod.choices)
    by_method = {labels.get(row["method"], row["method"]): row["total"]
                 for row in payments.order_by().values("method").annotate(total=Sum("amount"))}
    return render(request, "billing/payment_list.html", {
        "form": form, "page_obj": Paginator(payments, PER_PAGE).get_page(request.GET.get("page")),
        "date_from": date_from, "date_to": date_to, "places_shown": shown,
        "total": sum(by_method.values(), Decimal("0")), "by_method": sorted(by_method.items()),
    })


# ------------------------------------------------------------ bills
@role_required(*FRONT_DESK, *CLINICAL)
def bill_create(request):
    """A new bill: the patient, the services (several at once, with teeth and discounts) and, at the reception,
    the payment if the patient pays now. Then the bill prints.

    A dentist writes the bill of their work but never the payment: the bill goes to the reception of the place,
    who records what the patient paid and how."""
    at_desk = has_role(request.user, *FRONT_DESK)
    me = None if at_desk else Dentist.for_user(request.user)
    patient = appointment = None
    if request.GET.get("appointment", "").isdigit():
        appointment = Appointment.objects.filter(pk=request.GET["appointment"], patient__in=Patient.objects.here()
                                                 ).select_related("patient", "dentist").first()
        patient = appointment.patient if appointment else None
    if patient is None and request.GET.get("patient", "").isdigit():
        patient = Patient.objects.here().filter(pk=request.GET["patient"]).first()
    here = appointment.branch if appointment is not None else branch_for_user(request.user)
    initial = {"billed_on": timezone.localdate(), "dentist": appointment.dentist if appointment else me}
    form = BillForm(request.POST or None, patient=patient, initial=initial, branch=here)
    quick = request.GET.get("service", "")
    lines = BillLineFormSet(request.POST or None, prefix="lines", form_kwargs={"branch": here},
                            initial=[{"service": int(quick)}] if quick.isdigit() else None)
    pay = PayNowForm(request.POST or None, prefix="pay") if at_desk else None
    if request.method == "POST" and form.is_valid() and lines.is_valid() and (pay is None or pay.is_valid()):
        chosen = [line.cleaned_data for line in lines if line.cleaned_data.get("service")]
        bill = create_bill(form.cleaned_data["patient_lookup"], chosen, request.user,
                           billed_on=form.cleaned_data["billed_on"], appointment=appointment,
                           dentist=form.cleaned_data.get("dentist") or me, notes=form.cleaned_data.get("notes", ""),
                           branch=here, source=Bill.Source.RECEPTION if at_desk else Bill.Source.DENTIST)
        amount = pay.cleaned_data.get("amount") if pay is not None else None
        if amount:
            payment = PatientPayment.objects.create(
                patient=bill.patient, bill=bill, amount=amount, branch=bill.branch,
                paid_on=bill.billed_on, method=pay.cleaned_data["method"], reference=pay.cleaned_data.get("reference", ""),
                fawry_machine=pay.cleaned_data.get("fawry_machine"), created_by=request.user,
            )
            messages.success(request, _("Bill %(number)s saved, and the payment of %(amount)s (%(method)s): receipt "
                                        "%(receipt)s.") % {"number": bill.number, "amount": f"{payment.amount:,.2f}",
                                                           "method": payment.get_method_display(),
                                                           "receipt": payment.receipt_number})
        elif not at_desk:
            send_bill_to_reception(bill, request.user)
            tell_price_changes(bill, request.user, [(line["service"], line.get("teeth", ""), line.get("price"))
                                                    for line in chosen])
            messages.success(request, _("Bill %(number)s sent to the reception to collect.") % {"number": bill.number})
        else:
            messages.success(request, _("Bill %(number)s saved.") % {"number": bill.number})
        return redirect(bill)
    from apps.clinics.prices import prices_at

    doctor_prices = {}
    for (dentist_id, service_id), row in prices_at(here).items():
        doctor_prices.setdefault(str(dentist_id), {})[str(service_id)] = f"{row.price:.2f}"
    return render(request, "billing/bill_form.html", {
        "form": form, "lines": lines, "pay": pay, "patient": patient, "appointment": appointment, "place": here,
        "quick_services": Service.for_place(here).filter(quick_button=True), "at_desk": at_desk,
        "doctor_prices": doctor_prices,
    })


def tell_price_changes(bill, user, wanted):
    """A dentist wrote another price than the usual one (round 15): the clinic manager of the place and the owner
    are told. ``wanted`` is [(service, teeth, price typed or None)], the lines as the dentist wrote them."""
    from apps.clinics.prices import price_and_cost
    from apps.core.roles import MODERATOR

    changed = []
    for service, teeth, price in wanted:
        if price is None:
            continue
        usual, _cost = price_and_cost(service, bill.dentist, bill.branch, teeth)
        if price != usual:
            changed.append(f"{service}: {usual:,.2f} → {price:,.2f}")
    if not changed:
        return []
    people = list(staff_at(bill.branch, MODERATOR)) + list(staff_at(None, OWNER))
    notify_users(people, gettext_lazy("Price changed by %(dentist)s: %(patient)s"), "%(lines)s",
                 bill.get_absolute_url(), Notification.Level.WARNING, exclude=user,
                 params={"dentist": str(bill.dentist or user), "patient": bill.patient.full_name,
                         "lines": " · ".join(changed)})
    return changed


def send_bill_to_reception(bill, user):
    """Tell the reception of the bill's place that a dentist's bill waits to be collected."""
    notify_users(staff_at(bill.branch, SECRETARY), gettext_lazy("A bill to collect: %(patient)s"),
                 gettext_lazy("%(number)s from %(dentist)s: %(total)s"), bill.get_absolute_url(),
                 Notification.Level.WARNING, exclude=user,
                 params={"patient": bill.patient.full_name, "number": bill.number, "dentist": str(bill.dentist or user),
                         "total": f"{bill.totals()['net']:,.2f}"})


def bill_detail(request, pk, pay_form=None):
    """The printed bill (the reception, and the dentists for the bills of their work)."""
    bill = get_object_or_404(Bill.objects.select_related("patient", "dentist", "created_by"), pk=pk)
    if not has_role(request.user, *FRONT_DESK):
        me = Dentist.for_user(request.user)
        mine = bill.created_by_id == request.user.pk or (me is not None and bill.dentist_id == me.pk)
        if not has_role(request.user, *CLINICAL) or not mine:
            raise PermissionDenied
    current = account(bill.patient)
    return render(request, "billing/bill.html", {
        "bill": bill, "totals": bill.totals(current), "account": current,
        "payments": bill.payments.order_by("paid_on", "pk"), "a4": bool(request.GET.get("a4")),
        "pay_form": pay_form or (PayNowForm(prefix="pay") if has_role(request.user, *FRONT_DESK) else None),
    })


@role_required(*FRONT_DESK)
def bill_pay(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    pay = PayNowForm(request.POST or None, prefix="pay")
    if request.method == "POST" and pay.is_valid() and pay.cleaned_data.get("amount"):
        payment = PatientPayment.objects.create(
            patient=bill.patient, bill=bill, amount=pay.cleaned_data["amount"], method=pay.cleaned_data["method"],
            reference=pay.cleaned_data.get("reference", ""), created_by=request.user, branch=bill.branch,
            fawry_machine=pay.cleaned_data.get("fawry_machine"))
        messages.success(request, _("Payment saved: %(amount)s (%(method)s). Receipt %(number)s.") % {
            "amount": f"{payment.amount:,.2f}", "method": payment.get_method_display(), "number": payment.receipt_number})
        return redirect(payment)
    if request.method == "POST":
        # Show the form again as it was filled, with the problem next to the box (the chosen method is kept).
        if pay.is_valid():
            pay.add_error("amount", _("Write the amount paid."))
        messages.error(request, _("The payment was not saved: see the red note in the form."))
        return bill_detail(request, pk, pay_form=pay)
    return redirect(bill)


@role_required(*FRONT_DESK)
def bill_list(request):
    """The bills of a period; "not fully paid" shows what is left to collect (e.g. bills the dentists added)."""
    today = timezone.localdate()
    here, places = branch_for_user(request.user), list(working_places(request.user))
    form = BillFilterForm(request.GET or None, places=places, current=here)
    data = form.cleaned_data if form.is_valid() else {}
    date_from, date_to = data.get("date_from") or today, data.get("date_to") or today
    shown = chosen_places(form, places, here)
    bills = list(Bill.objects.filter(billed_on__range=(date_from, date_to), branch__in=shown)
                 .select_related("patient", "dentist", "branch"))
    rows, all_totals = [], bill_totals(bills)
    for bill in bills:
        totals = all_totals[bill.pk]
        if data.get("unpaid") and totals["left"] <= 0:
            continue
        rows.append({"bill": bill, **totals})
    return render(request, "billing/bill_list.html", {
        "form": form, "rows": rows, "page_obj": Paginator(rows, PER_PAGE).get_page(request.GET.get("page")),
        "date_from": date_from, "date_to": date_to, "places_shown": shown,
        "total_net": sum((r["net"] for r in rows), Decimal("0")),
        "total_left": sum((r["left"] for r in rows), Decimal("0")),
    })


# ------------------------------------------------------------ the Fawry machine
@role_required(*FRONT_DESK)
def fawry_ledger(request):
    """Every move through the Fawry POS machine, with the money still held at Fawry. Each person sees the moves they
    did (round 13); the owner and the head of CIA see every move, the money held at Fawry and the percentage."""
    today = timezone.localdate()
    sees_all = has_role(request.user, OWNER, HEAD_CIA)
    form = FawryFilterForm(request.GET or None, sees_all=sees_all)
    data = form.cleaned_data if form.is_valid() else {}
    date_from = data.get("date_from") or today.replace(day=1)
    date_to = data.get("date_to") or today
    if not form.is_bound:
        form = FawryFilterForm(initial={"date_from": date_from, "date_to": date_to}, sees_all=sees_all)
    moves = FawryMove.objects.filter(moved_on__range=(date_from, date_to)).select_related(
        "branch", "machine", "created_by", "patient_payment__patient", "academy_payment__enrollment", "purchase")
    if not sees_all:
        moves = moves.filter(created_by=request.user)
    elif data.get("person"):
        moves = moves.filter(created_by=data["person"])
    filtered = bool(data.get("branch") or data.get("kind") or data.get("person")) or not sees_all
    machine = data.get("machine")
    if machine is not None:
        moves = moves.filter(machine=machine)
    if data.get("branch"):
        moves = moves.filter(branch=data["branch"])
    if data.get("kind"):
        moves = moves.filter(kind=data["kind"])
    on_machine = FawryMove.objects.filter(machine=machine) if machine is not None else None
    opening = fawry.held_at_fawry(until=date_from - timedelta(days=1), moves=on_machine) if sees_all else None
    rows = list(moves.order_by("moved_on", "pk"))
    running = opening or Decimal("0")
    for move in rows:
        running += move.balance_change
        move.running = running
    rows.reverse()
    totals = fawry.totals(moves)
    options = ClinicSettings.get()
    context = {
        "form": form, "date_from": date_from, "date_to": date_to, "moves": rows, "filtered": filtered,
        "totals": totals, "kept": totals["fees"] + totals[FawryMove.Kind.CHARGE], "machine": machine,
        "fee_percent": options.fawry_fee_percent, "can_correct": sees_all, "sees_all": sees_all,
    }
    if sees_all:
        context.update({
            "opening": opening, "closing": fawry.held_at_fawry(until=date_to, moves=on_machine),
            "held_now": fawry.held_at_fawry(),
            "per_machine": [(m, fawry.held_at_fawry(moves=FawryMove.objects.filter(machine=m)))
                            for m in FawryMachine.objects.all() if m.is_active or m.moves.exists()],
        })
    if has_role(request.user, OWNER):
        context["percent_form"] = FawryPercentForm(initial={"percent": options.fawry_fee_percent})
    return render(request, "billing/fawry.html", context)


@role_required(OWNER)
@require_POST
def fawry_percent(request):
    """The owner changes Fawry's percentage here (also in Settings → Clinic options). Card payments taken from now on
    use it; the moves already written keep theirs (each can be corrected)."""
    form = FawryPercentForm(request.POST)
    if form.is_valid():
        options = ClinicSettings.get()
        options.fawry_fee_percent = form.cleaned_data["percent"]
        options.save(update_fields=["fawry_fee_percent"])
        messages.success(request, _("Fawry's percentage is now %(percent)s%%. It is used for the card payments taken "
                                    "from now on.") % {"percent": f"{form.cleaned_data['percent']:g}"})
    else:
        messages.error(request, _("Write the percentage as a number from 0 to 20, e.g. 1.5."))
    return redirect("billing:fawry")


@role_required(*FRONT_DESK)
def fawry_move_create(request):
    form = FawryMoveForm(request.POST or None, initial={"kind": request.GET.get("kind") or FawryMove.Kind.SERVICE})
    if request.method == "POST" and form.is_valid():
        move = form.save(commit=False)
        move.created_by = request.user
        move.save()
        messages.success(request, _("Fawry move %(number)s saved.") % {"number": move.number})
        return redirect("billing:fawry")
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("New Fawry move"), "cancel_url": reverse("billing:fawry"),
    })


@role_required(OWNER, HEAD_CIA)
def fawry_move_update(request, pk):
    move = get_object_or_404(FawryMove, pk=pk)
    form = FawryMoveForm(request.POST or None, instance=move)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Fawry move %(number)s corrected.") % {"number": move.number})
        return redirect("billing:fawry")
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Correct Fawry move %(number)s") % {"number": move.number},
        "cancel_url": reverse("billing:fawry"),
    })


@role_required(OWNER, HEAD_CIA)
@require_POST
def fawry_move_delete(request, pk):
    move = get_object_or_404(FawryMove, pk=pk)
    if move.is_automatic:
        messages.error(request, _("This move comes from a payment or a purchase: change or delete that instead."))
    else:
        move.delete()
        messages.success(request, _("Fawry move deleted."))
    return redirect("billing:fawry")
