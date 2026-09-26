"""Implants in stock, by company, size and lot: the surgery chart offers them and takes each
placed implant out of stock (one piece of that lot), putting it back if the tooth is changed or removed."""

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from .models import StockItem, StockMovement
from .services import record_movement, undo_movement


def implant_items(system=None, diameter=None, length=None):
    items = StockItem.objects.filter(is_active=True, implant_system__isnull=False, implant_diameter__isnull=False,
                                     implant_length__isnull=False).select_related("implant_system")
    if system:
        items = items.filter(implant_system=system)
    if diameter:
        items = items.filter(implant_diameter=diameter)
    if length:
        items = items.filter(implant_length=length)
    return items.order_by("implant_system__company", "implant_diameter", "implant_length")


def choice_value(item_id, lot):
    return f"{item_id}|{lot}"


def parse_choice(value):
    """'12|LOT-A' -> (12, 'LOT-A'); None when empty or not valid."""
    item_id, sep, lot = (value or "").partition("|")
    if not sep or not item_id.isdigit():
        return None
    return int(item_id), lot


def lot_choices(system=None, diameter=None, length=None, keep=None):
    """Lots in stock for the chosen company (and size). ``keep`` (item_id, lot) is the lot this tooth
    already holds: it stays in the list even when the last piece is the one it took."""
    rows = []
    for item in implant_items(system, diameter, length):
        lots = item.lots()
        if keep and keep[0] == item.pk and not any(l["lot"] == keep[1] for l in lots):
            lots.append({"lot": keep[1], "left": Decimal("0"), "expiry": None})
        for lot in lots:
            size = f"{item.implant_diameter:g} x {item.implant_length:g}"
            parts = [str(item.implant_system), size, lot["lot"] or _("without lot number")]
            if lot["expiry"]:
                parts.append(_("exp. %(date)s") % {"date": lot["expiry"].strftime("%m/%Y")})
            parts.append(_("%(n)s left") % {"n": f"{lot['left']:g}"})
            rows.append({
                "value": choice_value(item.pk, lot["lot"]), "label": " — ".join(parts), "left": lot["left"],
                "system": item.implant_system_id, "diameter": f"{item.implant_diameter:g}",
                "length": f"{item.implant_length:g}", "lot": lot["lot"],
            })
    return rows


def available(item_id, lot):
    item = StockItem.objects.filter(pk=item_id).first()
    if item is None:
        return Decimal("0")
    return next((l["left"] for l in item.lots() if l["lot"] == lot), Decimal("0"))


@transaction.atomic
def take_implants(surgery, user):
    """Keep the stock in step with the implants of the chart: one piece out per tooth that names a lot from stock."""
    patient = surgery.patient.full_name
    for site in surgery.sites.select_related("stock_movement"):
        wanted = (site.implant_stock_item_id, site.lot_number) if site.implant_stock_item_id else None
        current = site.stock_movement
        if current is not None and wanted == (current.item_id, current.lot):
            continue
        if current is not None:
            site.stock_movement = None
            site.save(update_fields=["stock_movement"])
            undo_movement(current)
        if wanted is not None:
            movement = record_movement(
                site.implant_stock_item, StockMovement.Kind.OUT, 1, user, lot=site.lot_number,
                destination=_("Surgery %(number)s, tooth %(tooth)s") % {"number": surgery.number, "tooth": site.tooth},
                notes=patient[:255])
            site.stock_movement = movement
            site.save(update_fields=["stock_movement"])


def give_back(site):
    """A tooth removed from the chart (or the whole surgery deleted): its implant goes back to stock."""
    if site.stock_movement_id:
        movement = StockMovement.objects.filter(pk=site.stock_movement_id).first()
        if movement is not None:
            undo_movement(movement)
