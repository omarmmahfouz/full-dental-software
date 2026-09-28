from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.mixins import role_required
from apps.core.models import ClinicSettings, branch_for_user
from apps.core.roles import STOCK_ROLES
from apps.scheduling.models import day_bounds

from .forms import (
    ImportForm, MovementFilterForm, MovementForm, StockCategoryForm, StockFilterForm, StockItemForm, UseFormSet,
    UseHeaderForm,
)
from .importer import import_items, parse, read_rows
from .models import GROUP_LOOK, StockCategory, StockGroup, StockItem, StockMovement
from .services import record_movement

def low_stock():
    return StockItem.objects.filter(is_active=True).filter(
        Q(quantity__lte=0) | Q(min_quantity__gt=0, quantity__lte=F("min_quantity"))
    )


def expiring_soon(days=None):
    """Received batches whose expiry date is near, for items still in stock."""
    if days is None:
        days = ClinicSettings.get().stock_expiry_days
    limit = timezone.localdate() + timedelta(days=days)
    return (
        StockMovement.objects.filter(kind=StockMovement.Kind.IN, expiry_date__isnull=False, expiry_date__lte=limit,
                                     item__quantity__gt=0, item__is_active=True)
        .select_related("item")
        .order_by("expiry_date")
    )


def stock_groups(group=None):
    """The groups of the stock (dental, implants, beverage...) with how many items each has and how many are low,
    and the categories of the chosen group."""
    counts = dict(StockItem.objects.filter(is_active=True).values_list("category__group").annotate(n=Count("pk")))
    low = dict(low_stock().values_list("category__group").annotate(n=Count("pk")))
    with_categories = set(StockCategory.objects.filter(is_active=True).values_list("group", flat=True))
    groups = []
    for code, label in StockGroup.choices:
        if not counts.get(code) and code != group and code not in with_categories:
            continue
        icon, colour = GROUP_LOOK[code]
        groups.append({"code": code, "label": label, "icon": icon, "colour": colour, "count": counts.get(code, 0),
                       "low": low.get(code, 0), "active": code == group})
    categories = []
    if group:
        in_use = dict(StockItem.objects.filter(is_active=True, category__group=group).values_list("category")
                      .annotate(n=Count("pk")))
        categories = [(c, in_use.get(c.pk, 0)) for c in StockCategory.objects.filter(group=group, is_active=True)]
    return groups, categories


@role_required(*STOCK_ROLES)
def item_list(request):
    form = StockFilterForm(request.GET or None)
    items = StockItem.objects.select_related("category", "branch")
    group = request.GET.get("group") if request.GET.get("group") in StockGroup.values else None
    if group:
        items = items.filter(category__group=group)
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
        if data.get("place") == "shared":
            items = items.filter(branch__isnull=True)
        elif data.get("place"):
            items = items.filter(branch__code=data["place"])
    if not show_inactive:
        items = items.filter(is_active=True)
    # Group by group, then category, so each category is one block of the list.
    group_order = Case(*[When(category__group=code, then=Value(index)) for index, code in enumerate(StockGroup.values)],
                       output_field=IntegerField())
    items = items.order_by(group_order, "category__sort_order", "category__name_ar", "name")
    page = Paginator(items, 100).get_page(request.GET.get("page"))
    groups, categories = stock_groups(group)
    return render(request, "stock/item_list.html", {
        "filter_form": form, "page_obj": page, "low_count": low_stock().count(),
        "expiring_count": expiring_soon().values("item_id").distinct().count(),
        "expiry_days": ClinicSettings.get().stock_expiry_days,
        "groups": groups, "group": group, "group_categories": categories,
        "chosen_category": form.cleaned_data.get("category") if form.is_valid() else None,
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
                record_movement(obj, StockMovement.Kind.COUNT, opening, request.user, notes=_("Opening stock"),
                                branch=obj.branch)
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
                        initial={"kind": kind or StockMovement.Kind.OUT, "branch": item.branch or branch_for_user(request.user),
                                 "moved_at": timezone.localtime().replace(second=0, microsecond=0)})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        record_movement(item, data["kind"], data["quantity"], request.user, moved_at=data["moved_at"],
                        destination=data["destination"], lot=data["lot"], expiry_date=data["expiry_date"],
                        unit_cost=data["unit_cost"], notes=data["notes"],
                        branch=data["branch"] or item.branch or branch_for_user(request.user))
        messages.success(request, _("Stock updated."))
        return redirect(item)
    return render(request, "stock/item_detail.html", {
        "item": item, "form": form,
        "movements": item.movements.select_related("created_by", "purchase_item__purchase", "branch")[:200],
        "today": timezone.localdate(),
    })


@role_required(*STOCK_ROLES)
def use(request):
    """Take several items out of stock at once (e.g. what a room or the kitchen needs)."""
    header = UseHeaderForm(request.POST or None, initial={"branch": branch_for_user(request.user)})
    initial = []
    if request.GET.get("item", "").isdigit():
        initial = [{"item": request.GET["item"]}]
    formset = UseFormSet(request.POST or None, initial=initial, prefix="lines")
    if request.method == "POST" and header.is_valid() and formset.is_valid():
        lines = [f.cleaned_data for f in formset if f.cleaned_data.get("item")]
        place = header.cleaned_data["branch"] or branch_for_user(request.user)
        others = [line["item"] for line in lines if line["item"].branch_id and line["item"].branch_id != place.pk]
        if not lines:
            messages.error(request, _("Choose at least one item."))
        elif others:
            messages.error(request, _("%(item)s belongs to %(place)s: it cannot be used for %(here)s.")
                           % {"item": others[0], "place": others[0].branch, "here": place})
        else:
            with transaction.atomic():
                for line in lines:
                    record_movement(line["item"], header.cleaned_data["kind"], line["quantity"], request.user,
                                    destination=header.cleaned_data["destination"], notes=header.cleaned_data["notes"],
                                    branch=place)
            messages.success(request, _("%(n)s items taken out of stock.") % {"n": len(lines)})
            return redirect("stock:item_list")
    return render(request, "stock/use.html", {"header": header, "formset": formset})


@role_required(*STOCK_ROLES)
def movement_list(request):
    form = MovementFilterForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today - timedelta(days=30), today
    qs = StockMovement.objects.select_related("item__category", "created_by", "branch")
    if form.is_valid():
        data = form.cleaned_data
        date_from = data.get("date_from") or date_from
        date_to = data.get("date_to") or date_to
        if data.get("kind"):
            qs = qs.filter(kind=data["kind"])
        if data.get("category"):
            qs = qs.filter(item__category=data["category"])
        if data.get("group"):
            qs = qs.filter(item__category__group=data["group"])
        if data.get("q"):
            qs = qs.filter(Q(item__name__icontains=data["q"]) | Q(destination__icontains=data["q"]))
        if data.get("place"):
            qs = qs.filter(branch__code=data["place"])
    qs = qs.filter(moved_at__gte=day_bounds(date_from)[0], moved_at__lt=day_bounds(date_to)[1])
    page = Paginator(qs, 100).get_page(request.GET.get("page"))
    return render(request, "stock/movement_list.html", {
        "filter_form": form, "page_obj": page, "date_from": date_from, "date_to": date_to,
        "use_by_place": use_by_place(qs), "use_by_group": use_by_group(qs),
    })


def use_by_group(movements):
    """What was taken out of each group of the stock (dental, implants, beverage...) in the movements shown."""
    labels, rows = dict(StockGroup.choices), {}
    for m in movements.filter(kind__in=(StockMovement.Kind.OUT, StockMovement.Kind.WASTE)).select_related(
            "item__category"):
        code = m.item.category.group
        row = rows.setdefault(code, {"code": code, "label": labels.get(code, code), "icon": GROUP_LOOK[code][0],
                                     "moves": 0, "value": Decimal("0")})
        row["moves"] += 1
        row["value"] += m.quantity * (m.unit_cost or m.item.unit_cost or Decimal("0"))
    return sorted(rows.values(), key=lambda r: -r["value"])


@role_required(*STOCK_ROLES)
def categories(request):
    """The stock manager sees, adds and edits the categories of each group; each opens its items and moves."""
    category = get_object_or_404(StockCategory, pk=request.GET["edit"]) if request.GET.get("edit", "").isdigit() \
        else None
    form = StockCategoryForm(request.POST or None, instance=category,
                             initial={"group": request.GET.get("group")} if category is None else None)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, _("Category saved: %(name)s") % {"name": saved})
        return redirect(f"{reverse('stock:categories')}#group-{saved.group}")
    counts = dict(StockItem.objects.filter(is_active=True).values_list("category").annotate(n=Count("pk")))
    low = dict(low_stock().values_list("category").annotate(n=Count("pk")))
    by_group = {code: [] for code in StockGroup.values}
    for c in StockCategory.objects.all():
        by_group.setdefault(c.group, []).append({"category": c, "items": counts.get(c.pk, 0), "low": low.get(c.pk, 0)})
    groups = [{"code": code, "label": label, "icon": GROUP_LOOK[code][0], "colour": GROUP_LOOK[code][1],
               "rows": by_group.get(code, [])} for code, label in StockGroup.choices]
    return render(request, "stock/categories.html", {"form": form, "editing": category, "groups": groups})


def use_by_place(movements):
    """What each place took out of stock (used, damaged or expired) in the movements shown: pieces and value."""
    rows = {}
    for m in movements.filter(kind__in=(StockMovement.Kind.OUT, StockMovement.Kind.WASTE)).select_related("item", "branch"):
        row = rows.setdefault(m.branch_id, {"place": m.branch, "moves": 0, "value": Decimal("0")})
        row["moves"] += 1
        row["value"] += m.quantity * (m.unit_cost or m.item.unit_cost or Decimal("0"))
    return sorted(rows.values(), key=lambda r: -r["value"])


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
