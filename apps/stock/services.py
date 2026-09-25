"""Every stock change goes through ``record_movement`` so the item's quantity
and its movement history always agree."""

from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.core.models import Notification
from apps.core.notify import notify_roles
from apps.core.roles import STOCK

from .models import StockItem, StockMovement

K = StockMovement.Kind


@transaction.atomic
def record_movement(item, kind, quantity, user=None, **fields):
    """Apply a movement. ``quantity`` is positive; for a stock count it is the counted quantity."""
    item = StockItem.objects.select_for_update().get(pk=item.pk)
    quantity = Decimal(quantity)
    was_low = item.is_low
    if kind == K.IN:
        change = quantity
    elif kind == K.COUNT:
        change = quantity - item.quantity
    else:
        change = -quantity
    movement = StockMovement.objects.create(item=item, kind=kind, quantity=quantity, change=change,
                                            created_by=user, **fields)
    item.quantity += change
    update = ["quantity", "updated_at"]
    if kind == K.IN and fields.get("unit_cost") is not None:
        item.unit_cost = fields["unit_cost"]
        update.append("unit_cost")
    item.save(update_fields=update)
    if item.is_low and not was_low:
        notify_roles(
            (STOCK,), _("Low stock: %(item)s"), _("%(qty)s left (reorder level %(min)s)."),
            item.get_absolute_url(), Notification.Level.WARNING, exclude=user,
            params={"item": item.name, "qty": f"{item.quantity:g}", "min": f"{item.min_quantity:g}"},
        )
    return movement


@transaction.atomic
def undo_movement(movement):
    """Remove a movement and take its change back out of the item."""
    item = StockItem.objects.select_for_update().get(pk=movement.item_id)
    item.quantity -= movement.change
    item.save(update_fields=["quantity", "updated_at"])
    movement.delete()


@transaction.atomic
def sync_purchase(purchase, user):
    """Purchase lines that name a stock item are received into stock once.
    Editing the line (quantity or item) corrects the stock."""
    count = 0
    for line in purchase.items.select_related("stock_item"):
        existing = StockMovement.objects.filter(purchase_item=line).first()
        if existing is not None:
            if line.stock_item_id == existing.item_id and existing.quantity == line.quantity:
                continue
            undo_movement(existing)
        if line.stock_item_id:
            record_movement(line.stock_item, K.IN, line.quantity, user, purchase_item=line,
                            unit_cost=line.unit_price, moved_at=_purchase_time(purchase),
                            notes=f"{purchase.supplier} {purchase.invoice_number}".strip())
            count += 1
    return count


def _purchase_time(purchase):
    from datetime import datetime, time

    from django.utils import timezone

    if purchase.purchase_date == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.combine(purchase.purchase_date, time(12)))
