"""The prices of the stock items, from every purchase (round 13): each time an item is received with its unit price
(a purchase line that names it, or a receipt typed in the stock) the price is kept on the movement. These functions
follow how each price changed: the history of one item, the changes of a period, and the last price while buying."""

from decimal import Decimal

from .models import StockMovement


def _rows(items=None):
    """Every price paid, oldest first: (item id, when, unit price, supplier name, purchase id)."""
    movements = StockMovement.objects.filter(kind=StockMovement.Kind.IN, unit_cost__isnull=False)
    if items is not None:
        movements = movements.filter(item__in=items)
    return movements.order_by("item_id", "moved_at", "pk").values_list(
        "item_id", "moved_at", "unit_cost", "purchase_item__purchase__supplier__name", "purchase_item__purchase_id")


def change(old, new):
    """The change in percent from ``old`` to ``new`` (None without an old price)."""
    if old is None or not old:
        return None
    return ((new - old) * Decimal("100") / old).quantize(Decimal("0.1"))


def history(item):
    """The prices paid for one item, newest first, each with its change from the price before."""
    rows, before = [], None
    for _item, when, price, supplier, purchase in _rows([item]):
        rows.append({"at": when, "price": price, "supplier": supplier or "", "purchase": purchase,
                     "change": change(before, price)})
        before = price
    rows.reverse()
    prices = [row["price"] for row in rows]
    summary = None
    if prices:
        cheapest = min(rows, key=lambda row: row["price"])
        summary = {"last": prices[0], "lowest": min(prices), "highest": max(prices),
                   "average": (sum(prices) / len(prices)).quantize(Decimal("0.01")),
                   "cheapest_supplier": cheapest["supplier"], "times": len(prices)}
    return rows, summary


def changes(date_from, date_to, category=None):
    """The items whose price changed in the period: their last price there against the price before it, biggest
    rise first. {"item", "before", "before_at", "price", "at", "supplier", "change"}."""
    from datetime import datetime, time

    from django.utils import timezone

    from .models import StockItem

    start = timezone.make_aware(datetime.combine(date_from, time.min))
    end = timezone.make_aware(datetime.combine(date_to, time.max))
    last = {}
    for item_id, when, price, supplier, _purchase in _rows():
        entry = last.setdefault(item_id, {"in": None, "before": None})
        if when < start:
            entry["before"] = (price, when)
        elif when <= end:
            if entry["in"] is not None:
                entry["before"] = (entry["in"]["price"], entry["in"]["at"])
            entry["in"] = {"price": price, "at": when, "supplier": supplier or ""}
    found = {pk: entry for pk, entry in last.items()
             if entry["in"] is not None and entry["before"] is not None and entry["before"][0] != entry["in"]["price"]}
    items = StockItem.objects.in_bulk(list(found))
    rows = []
    for pk, entry in found.items():
        item = items.get(pk)
        if item is None or (category is not None and item.category_id != category.pk):
            continue
        rows.append({"item": item, "before": entry["before"][0], "before_at": entry["before"][1],
                     "price": entry["in"]["price"], "at": entry["in"]["at"], "supplier": entry["in"]["supplier"],
                     "change": change(entry["before"][0], entry["in"]["price"])})
    rows.sort(key=lambda row: -(row["change"] or 0))
    return rows


def last_prices(items):
    """{item id: {"price", "at", "supplier"}}: the last price paid for each item (the purchase form shows it)."""
    last = {}
    for item_id, when, price, supplier, _purchase in _rows(items):
        last[item_id] = {"price": str(price), "at": when.strftime("%d/%m/%Y"), "supplier": supplier or ""}
    return last


def before_purchase(purchase):
    """{purchase line id: (price before, change %)}: each line's price against the price paid before this purchase."""
    lines = {line.stock_item_id: line for line in purchase.items.all() if line.stock_item_id}
    result, before = {}, {}
    for item_id, _when, price, _supplier, purchase_id in _rows(list(lines)):
        if purchase_id == purchase.pk:
            line = lines[item_id]
            if item_id in before:
                result[line.pk] = (before[item_id], change(before[item_id], line.unit_price))
            continue
        before[item_id] = price
    return result


