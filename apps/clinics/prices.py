"""The price of a service for a doctor at a place: his own price when he has one (e.g. the TMJ specialist's
examination), else the price list's; and the usual lab or implant cost of it, for each tooth."""

from decimal import Decimal

from .models import DoctorPrice


def prices_at(branch, dentists=None):
    """{(doctor pk, service pk): DoctorPrice} of the doctors' own prices at a place."""
    rows = DoctorPrice.objects.filter(branch=branch, is_active=True)
    if dentists is not None:
        rows = rows.filter(dentist__in=dentists)
    return {(row.dentist_id, row.service_id): row for row in rows}


def price_and_cost(service, dentist, branch, teeth=""):
    """(price, cost) of one bill line: the doctor's own price if any, and the usual cost times the teeth."""
    from .shares import teeth_count

    own = None
    if dentist is not None and branch is not None:
        own = DoctorPrice.objects.filter(dentist=dentist, branch=branch, service=service, is_active=True).first()
    price = own.price if own is not None else service.price
    unit_cost = own.cost if own is not None and own.cost is not None else (service.cost or Decimal("0"))
    return price, unit_cost * teeth_count(teeth) if unit_cost else Decimal("0")
