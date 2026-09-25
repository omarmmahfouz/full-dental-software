from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.mixins import role_required
from apps.core.roles import STOCK_ROLES
from apps.scheduling.models import day_bounds

from .forms import ImportForm, MovementFilterForm, MovementForm, StockFilterForm, StockItemForm, UseFormSet, UseHeaderForm
from .importer import import_items, parse, read_rows
from .models import StockCategory, StockItem, StockMovement
from .services import record_movement

EXPIRY_DAYS = 60


def low_stock():
    return StockItem.objects.filter(is_active=True).filter(
        Q(quantity__lte=0) | Q(min_quantity__gt=0, quantity__lte=F("min_quantity"))
    )


def expiring_soon(days=EXPIRY_DAYS):
    """Received batches whose expiry date is near, for items still in stock."""
    limit = timezone.localdate() + timedelta(days=days)
    return (
        StockMovement.objects.filter(kind=StockMovement.Kind.IN, expiry_date__isnull=False, expiry_date__lte=limit,
                                     item__quantity__gt=0, item__is_active=True)
        .select_related("item")
        .order_by("expiry_date")
    )


@role_required(*STOCK_ROLES)
def item_list(request):
    form = StockFilterForm(request.GET or None)
    items = StockItem.objects.select_related("category")
    show_inactive = False
    if form.is_valid():
        data = form.cleaned_data
        show_inactive = data.get("inactive")
        if data.get("q"):
            items = items.filter(Q(name__icontains=data["q"]) | Q(code__icontains=data["q"]) | Q(location__icontains=data["q"]))
        if data.get("category"):
            items = items.filter(category=data["category"])
        if data.get("low"):
            items = items.filter(pk__in=low_stock().values("pk"))
        if data.get("expiring"):
            items = items.filter(pk__in=expiring_soon().values("item_id"))
    if not show_inactive:
        items = items.filter(is_active=True)
    page = Paginator(items, 100).get_page(request.GET.get("page"))
    return render(request, "stock/item_list.html", {
        "filter_form": form, "page_obj": page, "low_count": low_stock().count(),
        "expiring_count": expiring_soon().values("item_id").distinct().count(),
        "categories": StockCategory.objects.filter(is_active=True),
    })


@role_required(*STOCK_ROLES)
def item_edit(request, pk=None):
    item = get_object_or_404(StockItem, pk=pk) if pk else None
    form = StockItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            opening = form.cleaned_data.get("opening_quantity")
            if opening:
                record_movement(obj, StockMovement.Kind.COUNT, opening, request.user, notes=_("Opening stock"))
        messages.success(request, _("Stock item saved."))
        return redirect(obj)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Edit stock item") if item else _("New stock item"),
        "cancel_url": item.get_absolute_url() if item else None,
    })


@role_required(*STOCK_ROLES)
def item_detail(request, pk):
    item = get_object_or_404(StockItem.objects.select_related("category"), pk=pk)
    kind = request.GET.get("kind") if request.method == "GET" else None
    form = MovementForm(request.POST or None, item=item,
                        initial={"kind": kind or StockMovement.Kind.OUT, "moved_at": timezone.localtime().replace(second=0, microsecond=0)})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        record_movement(item, data["kind"], data["quantity"], request.user, moved_at=data["moved_at"],
                        destination=data["destination"], lot=data["lot"], expiry_date=data["expiry_date"],
                        unit_cost=data["unit_cost"], notes=data["notes"])
        messages.success(request, _("Stock updated."))
        return redirect(item)
    return render(request, "stock/item_detail.html", {
        "item": item, "form": form, "movements": item.movements.select_related("created_by", "purchase_item__purchase")[:200],
        "today": timezone.localdate(),
    })


@role_required(*STOCK_ROLES)
def use(request):
    """Take several items out of stock at once (e.g. what a room or the kitchen needs)."""
    header = UseHeaderForm(request.POST or None)
    initial = []
    if request.GET.get("item", "").isdigit():
        initial = [{"item": request.GET["item"]}]
    formset = UseFormSet(request.POST or None, initial=initial, prefix="lines")
    if request.method == "POST" and header.is_valid() and formset.is_valid():
        lines = [f.cleaned_data for f in formset if f.cleaned_data.get("item")]
        if not lines:
            messages.error(request, _("Choose at least one item."))
        else:
            with transaction.atomic():
                for line in lines:
                    record_movement(line["item"], header.cleaned_data["kind"], line["quantity"], request.user,
                                    destination=header.cleaned_data["destination"], notes=header.cleaned_data["notes"])
            messages.success(request, _("%(n)s items taken out of stock.") % {"n": len(lines)})
            return redirect("stock:item_list")
    return render(request, "stock/use.html", {"header": header, "formset": formset})


@role_required(*STOCK_ROLES)
def movement_list(request):
    form = MovementFilterForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today - timedelta(days=30), today
    qs = StockMovement.objects.select_related("item__category", "created_by")
    if form.is_valid():
        data = form.cleaned_data
        date_from = data.get("date_from") or date_from
        date_to = data.get("date_to") or date_to
        if data.get("kind"):
            qs = qs.filter(kind=data["kind"])
        if data.get("category"):
            qs = qs.filter(item__category=data["category"])
        if data.get("q"):
            qs = qs.filter(Q(item__name__icontains=data["q"]) | Q(destination__icontains=data["q"]))
    qs = qs.filter(moved_at__gte=day_bounds(date_from)[0], moved_at__lt=day_bounds(date_to)[1])
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    return render(request, "stock/movement_list.html", {
        "filter_form": form, "page_obj": page, "date_from": date_from, "date_to": date_to,
    })


@role_required(*STOCK_ROLES)
def import_list(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            entries = parse(read_rows(form.cleaned_data["file"]))
        except Exception:  # noqa: BLE001 - a broken file is reported, not a crash
            entries = None
        if not entries:
            messages.error(request, _("No items could be read from this file."))
        else:
            created, updated = import_items(entries, form.cleaned_data["category"], request.user,
                                            as_count=form.cleaned_data["as_count"],
                                            note=_("Imported from %(file)s") % {"file": form.cleaned_data["file"].name})
            messages.success(request, _("%(n)s rows read: %(c)s new items, %(u)s existing items updated.")
                             % {"n": len(entries), "c": created, "u": updated})
            return redirect("stock:item_list")
    return render(request, "stock/import.html", {"form": form})
