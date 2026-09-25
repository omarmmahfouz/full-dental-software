from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.mixins import role_required
from apps.core.roles import FRONT_DESK
from apps.patients.models import Patient

from .forms import ChargeForm, PatientPaymentForm, PaymentFilterForm
from .models import PatientPayment, account


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
