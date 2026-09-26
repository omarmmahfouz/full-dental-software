"""The Fawry POS machine: every move of money through it and what is held at Fawry.

Payments taken on the machine (patients, course candidates) and purchases paid through it are
kept in step here by themselves; the reception adds the bills paid through the machine, the money
put on it and Fawry's transfers to the bank."""

from decimal import Decimal

from django.db.models import Sum

from apps.academy.models import PaymentMethod
from apps.core.models import ClinicSettings

from .models import FawryMove, PatientPayment

CENT = Decimal("0.01")


def fee_for(amount):
    percent = ClinicSettings.get().fawry_fee_percent or Decimal("0")
    return (Decimal(amount) * percent / 100).quantize(CENT)


def _details(source):
    """(field, kind, branch, date, amount, method, reference, description) of a payment or a purchase.
    The receipt number is not in the description: it is given just after the payment is saved."""
    from apps.academy.models import Payment
    from apps.purchasing.models import Purchase

    if isinstance(source, PatientPayment):
        return ("patient_payment", FawryMove.Kind.COLLECTION, source.patient.branch, source.paid_on, source.amount,
                source.method, source.reference, source.patient.full_name)
    if isinstance(source, Payment):
        enrollment = source.enrollment
        return ("academy_payment", FawryMove.Kind.COLLECTION, enrollment.course.branch, source.paid_on, source.amount,
                source.method, source.reference, f"{enrollment.candidate} ({enrollment.course.code})")
    if isinstance(source, Purchase):
        return ("purchase", FawryMove.Kind.SERVICE, source.branch, source.purchase_date, source.paid,
                source.payment_method, source.invoice_number, f"{source.supplier}")
    raise TypeError(source)


def sync(source):
    """Add, change or remove the Fawry move of a payment or a purchase after it is saved."""
    field, kind, branch, day, amount, method, reference, description = _details(source)
    move = FawryMove.objects.filter(**{field: source}).first()
    if method != PaymentMethod.FAWRY or not amount or amount <= 0:
        if move is not None:
            move.delete()
        return None
    if move is None:
        move = FawryMove(**{field: source})
        move.fee = fee_for(amount) if kind == FawryMove.Kind.COLLECTION else Decimal("0")
    elif move.amount != amount and kind == FawryMove.Kind.COLLECTION:
        move.fee = fee_for(amount)
    move.kind, move.branch, move.moved_on, move.amount = kind, branch, day, amount
    move.reference, move.description = reference[:100], description[:255]
    if kind == FawryMove.Kind.SERVICE:
        move.service = FawryMove.Service.SUPPLIER
    move.save()
    return move


def held_at_fawry(until=None, moves=None):
    """The money still at Fawry: card payments less its fee, plus money put on the machine,
    less bills paid through it, transfers to the bank and its other charges."""
    moves = FawryMove.objects.all() if moves is None else moves
    if until is not None:
        moves = moves.filter(moved_on__lte=until)
    total = Decimal("0")
    for row in moves.values("kind").annotate(amount=Sum("amount"), fee=Sum("fee")):
        if row["kind"] in FawryMove.MONEY_IN:
            total += row["amount"] - row["fee"]
        else:
            total -= row["amount"] + row["fee"]
    return total


def totals(moves):
    """Sums of a set of moves, by kind, for the ledger and the balance sheet."""
    result = {kind: Decimal("0") for kind in FawryMove.Kind.values}
    result.update(fees=Decimal("0"), cash_received=Decimal("0"), own_bills=Decimal("0"))
    for row in moves.values("kind", "purchase").annotate(amount=Sum("amount"), fee=Sum("fee"),
                                                          cash=Sum("cash_received")):
        result[row["kind"]] += row["amount"]
        result["fees"] += row["fee"]
        result["cash_received"] += row["cash"]
        if row["kind"] == FawryMove.Kind.SERVICE and row["purchase"] is None:
            result["own_bills"] += row["amount"]
    return result
