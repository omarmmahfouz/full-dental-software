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


def refund(payment, user, amount, method, reason, fawry_machine=None, charge=None):
    """Give money back on a paid receipt: a new receipt with the amount below zero (for one of its services when
    ``charge`` is given)."""
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
            patient=payment.patient, bill=payment.bill, charge=charge or payment.charge, branch=payment.branch,
            amount=-amount, method=method, fawry_machine=fawry_machine if method == PaymentMethod.FAWRY else None,
            refund_of=payment, notes=reason.strip()[:255], created_by=user)
        PaymentLog.objects.create(payment=payment, action=PaymentLog.Action.REFUNDED, before=_describe(payment),
                                  after=f"{back.receipt_number}: {_describe(back)}", reason=reason.strip()[:255],
                                  done_by=user)
    _tell_owner(payment, gettext_lazy("Money given back to a patient"), reason, user)
    return back


def service_receipts(patient):
    """For each service the patient paid: what is paid on it and the receipts that paid it, the latest first
    ({charge pk: {"paid", "receipts": [(payment, part)]}}): the refund is taken from them (round 15)."""
    from .models import _share_payments

    charges = list(patient.charges.select_related("service").order_by("charged_on", "pk"))
    payments = list(patient.patient_payments.order_by("paid_on", "pk"))
    detail = {}
    paid = _share_payments(charges, payments, detail)
    by_pk = {payment.pk: payment for payment in payments}
    rows = {charge.pk: {"charge": charge, "paid": paid[charge.pk], "receipts": []} for charge in charges}
    for payment_pk, parts in detail.items():
        payment = by_pk.get(payment_pk)
        if payment is None or payment.amount <= 0:
            continue
        for charge_pk, part in parts:
            rows[charge_pk]["receipts"].append((payment, part))
    for row in rows.values():
        row["receipts"].sort(key=lambda item: (item[0].paid_on, item[0].pk), reverse=True)
    return rows


def refund_services(patient, user, wanted, method, reason, fawry_machine=None, not_done=False):
    """Give money back for the services tapped (round 15): ``wanted`` is [(charge pk, amount)]. Each amount is taken
    from the receipts that paid that service, the latest first (one refund receipt for each receipt used). With
    ``not_done``, a service given back in full is taken off the account (a discount of 100%, with the reason), so
    the patient does not owe it again. Returns the refund receipts."""
    if not (reason or "").strip():
        raise ValidationError(_("Write why."))
    rows = service_receipts(patient)
    backs = []
    with transaction.atomic():
        for charge_pk, amount in wanted:
            row = rows.get(charge_pk)
            if row is None or amount <= 0:
                continue
            if amount > row["paid"]:
                raise ValidationError(_("%(service)s: at most %(amount)s can be given back.")
                                      % {"service": row["charge"].service, "amount": f"{row['paid']:,.2f}"})
            left = amount
            for payment, part in row["receipts"]:
                take = min(left, part, payment.refundable())
                if take <= 0:
                    continue
                backs.append(refund(payment, user, take, method, reason, fawry_machine, charge=row["charge"]))
                left -= take
                if left <= 0:
                    break
            if left > 0:
                raise ValidationError(_("%(service)s: its receipts were already given back.")
                                      % {"service": row["charge"].service})
            charge = row["charge"]
            if not_done and amount == row["paid"]:
                charge.discount_percent = Decimal("100")
                charge.discount_reason = (_("Given back: %(reason)s") % {"reason": reason.strip()})[:200]
                charge.save(update_fields=["discount_percent", "discount_reason", "updated_at"])
    return backs


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
    # The owner's money of the day (round 15): cash put in (or taken) counts in the drawer.
    from .models import OwnerCash

    owner = OwnerCash.objects.filter(moved_on__range=(date_from, date_to)).select_related("created_by")
    if branch is not None:
        owner = owner.filter(branch=branch)
    owner = list(owner)
    owner_cash = sum((move.signed for move in owner if move.method == PaymentMethod.CASH), ZERO)
    return {
        "owner_moves": owner, "owner_cash": owner_cash,
        "drawer": by_method.get(PaymentMethod.CASH, ZERO) + owner_cash,
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
