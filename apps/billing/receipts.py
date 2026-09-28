"""Checking the receipts: correct, cancel or refund one, and the end of the day at a place.

- A receipt is never deleted. A cancelled one stays in the day's list (crossed out) but counts nowhere.
- A refund is a receipt of its own, with the amount given back (below zero), linked to the paid one.
- Every change is written down (``PaymentLog``): who, when, why, and what the receipt was before. The owner is
  told of every cancellation and refund, and of corrections to an earlier day.
- The reception changes the receipts of today; the owner and the head of CIA any receipt."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.academy.models import PaymentMethod
from apps.core.models import Notification
from apps.core.notify import notify_roles
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, has_role

from .models import Bill, PatientPayment, PaymentLog

ZERO = Decimal("0")


def can_change(user, payment):
    """The owner and the head of CIA change any receipt; the reception the receipts of today."""
    if has_role(user, OWNER, HEAD_CIA):
        return True
    return has_role(user, *FRONT_DESK) and payment.paid_on == timezone.localdate()


def _describe(payment):
    machine = f" ({payment.fawry_machine})" if payment.fawry_machine_id else ""
    reference = f" #{payment.reference}" if payment.reference else ""
    return f"{payment.amount:,.2f} {payment.get_method_display()}{machine}{reference}"


def _tell_owner(payment, title, reason, user):
    notify_roles((OWNER,), title, gettext_lazy("%(number)s, %(patient)s: %(reason)s"), payment.get_absolute_url(),
                 Notification.Level.WARNING, exclude=user,
                 params={"number": payment.receipt_number, "patient": payment.patient.full_name, "reason": reason})


def _check(user, payment, reason):
    if not can_change(user, payment):
        raise PermissionDenied
    if payment.is_cancelled:
        raise ValidationError(_("This receipt is cancelled."))
    if not (reason or "").strip():
        raise ValidationError(_("Write why."))


def correct(payment, user, reason, **changes):
    """Change the amount, the payment method, the Fawry machine or the reference of a receipt."""
    _check(user, payment, reason)
    before = _describe(payment)
    with transaction.atomic():
        for name, value in changes.items():
            setattr(payment, name, value)
        if payment.method != PaymentMethod.FAWRY:
            payment.fawry_machine = None
        payment.save()
        PaymentLog.objects.create(payment=payment, action=PaymentLog.Action.CORRECTED, before=before,
                                  after=_describe(payment), reason=reason.strip()[:255], done_by=user)
    if payment.paid_on != timezone.localdate():
        _tell_owner(payment, gettext_lazy("A receipt of an earlier day was corrected"), reason, user)
    return payment


def cancel(payment, user, reason):
    """Cancel a receipt written by mistake: it stays in the list, crossed out, and counts nowhere."""
    _check(user, payment, reason)
    if payment.refunds.exists():
        raise ValidationError(_("This receipt has a refund: cancel the refund first."))
    with transaction.atomic():
        payment.cancelled_at, payment.cancelled_by, payment.cancel_reason = timezone.now(), user, reason.strip()[:255]
        payment.save()
        PaymentLog.objects.create(payment=payment, action=PaymentLog.Action.CANCELLED, before=_describe(payment),
                                  reason=payment.cancel_reason, done_by=user)
    _tell_owner(payment, gettext_lazy("A receipt was cancelled"), reason, user)
    return payment


def refund(payment, user, amount, method, reason, fawry_machine=None):
    """Give money back on a paid receipt: a new receipt with the amount below zero."""
    if not has_role(user, OWNER, HEAD_CIA, *FRONT_DESK):
        raise PermissionDenied
    if payment.is_cancelled:
        raise ValidationError(_("This receipt is cancelled."))
    if payment.is_refund:
        raise ValidationError(_("This receipt is itself a refund."))
    if not (reason or "").strip():
        raise ValidationError(_("Write why."))
    if not amount or amount <= 0 or amount > payment.refundable():
        raise ValidationError(_("The refund can be up to %(amount)s.") % {"amount": f"{payment.refundable():,.2f}"})
    with transaction.atomic():
        back = PatientPayment.objects.create(
            patient=payment.patient, bill=payment.bill, charge=payment.charge, branch=payment.branch,
            amount=-amount, method=method, fawry_machine=fawry_machine if method == PaymentMethod.FAWRY else None,
            refund_of=payment, notes=reason.strip()[:255], created_by=user)
        PaymentLog.objects.create(payment=payment, action=PaymentLog.Action.REFUNDED, before=_describe(payment),
                                  after=f"{back.receipt_number}: {_describe(back)}", reason=reason.strip()[:255],
                                  done_by=user)
    _tell_owner(payment, gettext_lazy("Money given back to a patient"), reason, user)
    return back


def day_summary(branch, date_from, date_to=None):
    """The receipts, bills and changes of a day (or a month) at a place, added up for the review."""
    date_to = date_to or date_from
    everything = PatientPayment.every.filter(paid_on__range=(date_from, date_to)).select_related(
        "patient", "created_by", "fawry_machine", "bill", "refund_of", "cancelled_by").order_by("paid_on", "pk")
    if branch is not None:
        everything = everything.filter(branch=branch)
    receipts = list(everything)
    live = [p for p in receipts if not p.is_cancelled]
    labels = dict(PaymentMethod.choices)
    by_method, by_person = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for payment in live:
        by_method[payment.method] += payment.amount
        by_person[payment.created_by] += payment.amount
    bills = Bill.objects.filter(billed_on__range=(date_from, date_to))
    if branch is not None:
        bills = bills.filter(branch=branch)
    from .models import bill_totals

    bills = list(bills.select_related("patient", "dentist"))
    totals = bill_totals(bills)
    changes = PaymentLog.objects.filter(done_at__date__range=(date_from, date_to)).select_related(
        "payment__patient", "done_by")
    if branch is not None:
        changes = changes.filter(payment__branch=branch)
    return {
        "receipts": receipts,
        "by_method": sorted(((labels.get(k, k), v, k) for k, v in by_method.items()), key=lambda row: -row[1]),
        "by_person": sorted(by_person.items(), key=lambda row: -row[1]),
        "total": sum((p.amount for p in live), ZERO),
        "cash": by_method.get(PaymentMethod.CASH, ZERO),
        "count": len([p for p in live if not p.is_refund]),
        "refunds": sum((p.amount for p in live if p.is_refund), ZERO),
        "cancelled": [p for p in receipts if p.is_cancelled],
        "bills": [{"bill": b, **totals[b.pk]} for b in bills],
        "billed": sum((totals[b.pk]["net"] for b in bills), ZERO),
        "left": sum((totals[b.pk]["left"] for b in bills), ZERO),
        "changes": list(changes),
    }
