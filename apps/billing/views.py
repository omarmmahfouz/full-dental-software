from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import ClinicSettings
from apps.core.roles import CLINICAL, FRONT_DESK, HEAD_CIA, OWNER, has_role
from apps.dentists.models import Dentist
from apps.patients.models import Patient
from apps.scheduling.models import Appointment

from . import fawry
from .forms import (
    BillFilterForm,
    BillForm,
    BillLineFormSet,
    ChargeForm,
    FawryFilterForm,
    FawryMoveForm,
    PatientPaymentForm,
    PaymentFilterForm,
    PayNowForm,
)
from .models import Bill, FawryMove, PatientPayment, Service, account, create_bill


@role_required(*FRONT_DESK)
def patient_account(request, pk):
    """The patient's services (price, discount, paid, left) and payments, with forms to add both."""
    patient = get_object_or_404(Patient, pk=pk)
    current = account(patient)
    action = request.POST.get("action")
    charge_form = ChargeForm(request.POST if action == "charge" else None, prefix="c",
                             initial={"charged_on": timezone.localdate()})
    payment_form = PatientPaymentForm(request.POST if action == "payment" else None, prefix="p", account=current,
                                      initial={"paid_on": timezone.localdate()})
    if action == "charge" and charge_form.is_valid():
        charge = charge_form.save(commit=False)
        charge.patient, charge.created_by = patient, request.user
        charge.save()
        messages.success(request, _("%(service)s added: %(net)s to pay.") % {"service": charge.service,
                                                                            "net": f"{charge.net:,.2f}"})
        return redirect("billing:account", pk=patient.pk)
    if action == "payment" and payment_form.is_valid():
        with transaction.atomic():
            payment = payment_form.save(commit=False)
            payment.patient, payment.created_by = patient, request.user
            payment.save()
        messages.success(request, _("Payment saved. Receipt %(number)s.") % {"number": payment.receipt_number})
        return redirect(payment)
    return render(request, "billing/account.html", {
        "patient": patient, "account": current, "charge_form": charge_form, "payment_form": payment_form,
    })


@role_required(*FRONT_DESK)
def receipt(request, pk):
    payment = get_object_or_404(PatientPayment.objects.select_related("patient", "charge__service", "created_by"),
                                pk=pk)
    return render(request, "billing/receipt.html", {"payment": payment, "account": account(payment.patient)})


@role_required(*FRONT_DESK)
def payment_list(request):
    """What the reception collected: by day, with the total for each payment method."""
    today = timezone.localdate()
    form = PaymentFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {}
    date_from, date_to = data.get("date_from") or today, data.get("date_to") or today
    payments = PatientPayment.objects.filter(paid_on__range=(date_from, date_to)).select_related(
        "patient", "charge__service", "created_by")
    if data.get("method"):
        payments = payments.filter(method=data["method"])
    by_method = defaultdict(lambda: Decimal("0"))
    for payment in payments:
        by_method[payment.get_method_display()] += payment.amount
    return render(request, "billing/payment_list.html", {
        "form": form, "payments": payments, "date_from": date_from, "date_to": date_to,
        "total": sum(by_method.values(), Decimal("0")), "by_method": sorted(by_method.items()),
    })


# ------------------------------------------------------------ bills
@role_required(*FRONT_DESK)
def bill_create(request):
    """A new bill: the patient, the services (several at once, with teeth and discounts) and,
    if the patient pays now, the payment. Then the bill prints."""
    patient = appointment = None
    if request.GET.get("appointment", "").isdigit():
        appointment = Appointment.objects.filter(pk=request.GET["appointment"]).select_related("patient", "dentist").first()
        patient = appointment.patient if appointment else None
    if patient is None and request.GET.get("patient", "").isdigit():
        patient = Patient.objects.filter(pk=request.GET["patient"]).first()
    initial = {"billed_on": timezone.localdate(), "dentist": appointment.dentist if appointment else None}
    form = BillForm(request.POST or None, patient=patient, initial=initial)
    quick = request.GET.get("service", "")
    lines = BillLineFormSet(request.POST or None, prefix="lines",
                            initial=[{"service": int(quick)}] if quick.isdigit() else None)
    pay = PayNowForm(request.POST or None, prefix="pay")
    if request.method == "POST" and form.is_valid() and lines.is_valid() and pay.is_valid():
        chosen = [line.cleaned_data for line in lines if line.cleaned_data.get("service")]
        bill = create_bill(form.cleaned_data["patient_lookup"], chosen, request.user,
                           billed_on=form.cleaned_data["billed_on"], appointment=appointment,
                           dentist=form.cleaned_data.get("dentist"), notes=form.cleaned_data.get("notes", ""))
        amount = pay.cleaned_data.get("amount")
        if amount:
            PatientPayment.objects.create(
                patient=bill.patient, bill=bill, amount=amount,
                paid_on=bill.billed_on, method=pay.cleaned_data["method"], reference=pay.cleaned_data.get("reference", ""),
                created_by=request.user,
            )
        messages.success(request, _("Bill %(number)s saved.") % {"number": bill.number})
        return redirect(bill)
    return render(request, "billing/bill_form.html", {
        "form": form, "lines": lines, "pay": pay, "patient": patient, "appointment": appointment,
        "quick_services": Service.objects.filter(is_active=True, quick_button=True),
    })


def bill_detail(request, pk):
    """The printed bill (the reception, and the dentists for the bills of their work)."""
    bill = get_object_or_404(Bill.objects.select_related("patient", "dentist", "created_by"), pk=pk)
    if not has_role(request.user, *FRONT_DESK):
        me = Dentist.for_user(request.user)
        if not has_role(request.user, *CLINICAL) or me is None or bill.dentist_id != me.pk:
            raise PermissionDenied
    current = account(bill.patient)
    return render(request, "billing/bill.html", {
        "bill": bill, "totals": bill.totals(current), "account": current,
        "payments": bill.payments.order_by("paid_on", "pk"),
        "pay_form": PayNowForm(prefix="pay") if has_role(request.user, *FRONT_DESK) else None,
    })


@role_required(*FRONT_DESK)
def bill_pay(request, pk):
    bill = get_object_or_404(Bill, pk=pk)
    pay = PayNowForm(request.POST or None, prefix="pay")
    if request.method == "POST" and pay.is_valid() and pay.cleaned_data.get("amount"):
        payment = PatientPayment.objects.create(
            patient=bill.patient, bill=bill, amount=pay.cleaned_data["amount"], method=pay.cleaned_data["method"],
            reference=pay.cleaned_data.get("reference", ""), created_by=request.user)
        messages.success(request, _("Payment saved. Receipt %(number)s.") % {"number": payment.receipt_number})
    else:
        for errors in pay.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(bill)


@role_required(*FRONT_DESK)
def bill_list(request):
    """The bills of a period; "not fully paid" shows what is left to collect (e.g. bills the dentists added)."""
    today = timezone.localdate()
    form = BillFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {}
    date_from, date_to = data.get("date_from") or today, data.get("date_to") or today
    bills = list(Bill.objects.filter(billed_on__range=(date_from, date_to)).select_related("patient", "dentist"))
    accounts, rows = {}, []
    for bill in bills:
        if bill.patient_id not in accounts:
            accounts[bill.patient_id] = account(bill.patient)
        totals = bill.totals(accounts[bill.patient_id])
        if data.get("unpaid") and totals["left"] <= 0:
            continue
        rows.append({"bill": bill, **totals})
    return render(request, "billing/bill_list.html", {
        "form": form, "rows": rows, "date_from": date_from, "date_to": date_to,
        "total_net": sum((r["net"] for r in rows), Decimal("0")),
        "total_left": sum((r["left"] for r in rows), Decimal("0")),
    })


# ------------------------------------------------------------ the Fawry machine
@role_required(*FRONT_DESK)
def fawry_ledger(request):
    """Every move through the Fawry POS machine, with the money still held at Fawry."""
    today = timezone.localdate()
    form = FawryFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {}
    date_from = data.get("date_from") or today.replace(day=1)
    date_to = data.get("date_to") or today
    if not form.is_bound:
        form = FawryFilterForm(initial={"date_from": date_from, "date_to": date_to})
    moves = FawryMove.objects.filter(moved_on__range=(date_from, date_to)).select_related(
        "branch", "created_by", "patient_payment__patient", "academy_payment__enrollment", "purchase")
    filtered = bool(data.get("branch") or data.get("kind"))
    if data.get("branch"):
        moves = moves.filter(branch=data["branch"])
    if data.get("kind"):
        moves = moves.filter(kind=data["kind"])
    opening = fawry.held_at_fawry(until=date_from - timedelta(days=1))
    rows = list(moves.order_by("moved_on", "pk"))
    running = opening
    for move in rows:
        running += move.balance_change
        move.running = running
    rows.reverse()
    totals = fawry.totals(moves)
    return render(request, "billing/fawry.html", {
        "form": form, "date_from": date_from, "date_to": date_to, "moves": rows, "filtered": filtered,
        "totals": totals, "kept": totals["fees"] + totals[FawryMove.Kind.CHARGE], "opening": opening, "closing": fawry.held_at_fawry(until=date_to),
        "held_now": fawry.held_at_fawry(), "fee_percent": ClinicSettings.get().fawry_fee_percent,
        "can_correct": has_role(request.user, OWNER, HEAD_CIA),
    })


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
