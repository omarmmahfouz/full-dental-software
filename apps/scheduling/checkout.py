"""The checkout (round 18): when a patient leaves, one screen with what was done, the money of the visit and the next
visit. The reception collects and books from it, instead of looking for the bill in one card and the dentist's note
for the next visit in another."""

from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.mixins import role_required
from apps.core.roles import FRONT_DESK
from apps.patients.access import get_visible_patient_or_403

from .models import Appointment, PatientRequest, day_bounds

ZERO = Decimal("0")


def checkout_facts(appointment):
    """What the reception needs when the patient of ``appointment`` leaves: the work of the visit, its bills with
    what is left on each, what he owes from before, today's receipts, the dentist's note for the next visit, the
    appointments already booked and the prescriptions to hand over."""
    from apps.billing.models import Bill, PatientPayment, account, bill_totals
    from apps.clinical.models import TreatmentStep
    from apps.prescriptions.models import Prescription

    patient = appointment.patient
    day = timezone.localtime(appointment.scheduled_at).date()
    start, end = day_bounds(day)
    steps = list(TreatmentStep.objects.filter(
        Q(appointment=appointment) | Q(patient=patient, performed_at__gte=start, performed_at__lt=end))
        .select_related("step_type", "operator").distinct().order_by("performed_at", "pk"))
    bills = list(Bill.objects.filter(Q(appointment=appointment) | Q(patient=patient, billed_on=day))
                 .select_related("dentist").distinct().order_by("pk"))
    totals = bill_totals(bills)
    rows = [{"bill": bill, "net": totals[bill.pk]["net"], "paid": totals[bill.pk]["paid"],
             "left": totals[bill.pk]["left"]} for bill in bills]
    to_collect = sum((row["left"] for row in rows if row["left"] > 0), ZERO)
    balance = account(patient)["balance"]
    upcoming = list(appointment.other_upcoming())
    asked = PatientRequest.objects.filter(patient=patient, status__in=PatientRequest.OPEN).select_related(
        "dentist", "step_type").first()
    next_visit = next((step.next_visit for step in steps if step.next_visit), "")
    needs_booking = not upcoming and not appointment.no_follow_up
    return {
        "day": day, "steps": steps, "bills": rows, "to_collect": to_collect, "balance": balance,
        "before": max(balance - to_collect, ZERO),  # what he owes on older visits
        "receipts": list(PatientPayment.objects.filter(patient=patient, paid_on=day).order_by("pk")),
        "next_visit": next_visit, "upcoming": upcoming, "asked": asked, "needs_booking": needs_booking,
        "prescriptions": list(Prescription.objects.filter(patient=patient, prescribed_on=day)),
        "no_bill": bool(steps) and not bills,
        "money_done": to_collect <= 0, "all_done": to_collect <= 0 and not needs_booking,
    }


def has_something(appointment):
    """Is there anything to do at the desk before this patient goes? (Money left on today's bills, a visit to book,
    work done with no bill, a prescription to hand.) When there is not, "Left" goes back to the board."""
    facts = checkout_facts(appointment)
    return bool(facts["to_collect"] > 0 or facts["needs_booking"] or facts["no_bill"] or facts["prescriptions"]
                or facts["before"] > 0)


def booking_url(appointment, facts):
    """The booking form filled for the next visit, coming back to this checkout when saved."""
    from urllib.parse import urlencode

    params = {"patient": appointment.patient_id, "purpose": facts["next_visit"] or appointment.purpose,
              "checkout": appointment.pk}
    asked = facts["asked"]
    if asked is not None and asked.status == PatientRequest.Status.APPROVED:
        params.update({"dentist": asked.dentist_id, "duration": asked.time_given, "request": asked.pk})
        if asked.step_type_id:
            params["procedure"] = asked.step_type_id
    elif appointment.dentist_id:
        params["dentist"] = appointment.dentist_id
    return f"{reverse('scheduling:appointment_create')}?{urlencode(params)}"


@role_required(*FRONT_DESK)
def checkout(request, pk):
    """The patient is leaving: collect what is left on today's bills (each with its own small form), book the next
    visit with what the dentist wrote for it, hand the prescription. Everything stays on this page."""
    from apps.billing.forms import PayNowForm
    from apps.billing.models import Bill
    from apps.billing.receipts import pay_bill

    appointment = get_object_or_404(Appointment.objects.select_related("patient", "dentist", "room", "procedure"),
                                    pk=pk)
    patient = get_visible_patient_or_403(request.user, appointment.patient_id)
    here = reverse("scheduling:checkout", args=[appointment.pk])
    bound = None
    if request.method == "POST" and request.POST.get("bill", "").isdigit():
        bill = get_object_or_404(Bill, pk=request.POST["bill"], patient=patient)
        bound = PayNowForm(request.POST, prefix=f"pay{bill.pk}")
        if bound.is_valid() and bound.cleaned_data.get("amount"):
            payment = pay_bill(bill, bound.cleaned_data, request.user)
            messages.success(request, _("Payment saved: %(amount)s (%(method)s). Receipt %(number)s.") % {
                "amount": f"{payment.amount:,.2f}", "method": payment.get_method_display(),
                "number": payment.receipt_number})
            return redirect(here)
        if bound.is_valid():
            bound.add_error("amount", _("Write the amount paid."))
        bound.bill_pk = bill.pk
        messages.error(request, _("The payment was not saved: see the red note in the form."))
    facts = checkout_facts(appointment)
    for row in facts["bills"]:
        if row["left"] > 0:
            prefix = f"pay{row['bill'].pk}"
            row["form"] = bound if bound is not None and bound.bill_pk == row["bill"].pk else \
                PayNowForm(prefix=prefix, initial={"amount": row["left"]})
    return render(request, "scheduling/checkout.html", {
        "a": appointment, "patient": patient, **facts, "book_url": booking_url(appointment, facts),
        "alerts": [str(c) for c in patient.medical_conditions.all() if c.is_alert],
    })
