from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.billing import fawry
from apps.core.mixins import AuditMixin, RoleRequiredMixin, role_required
from apps.core.models import branch_for_user
from apps.core.roles import PURCHASE_ROLES
from apps.stock.services import sync_purchase

from .forms import PurchaseFilterForm, PurchaseForm, PurchaseItemFormSet, SupplierForm, purchase_places
from .models import Purchase, PurchaseCategory, PurchaseItem, Supplier

LINE_TOTAL = ExpressionWrapper(F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=14, decimal_places=2))


class SupplierListView(RoleRequiredMixin, ListView):
    allowed_roles = PURCHASE_ROLES
    template_name = "purchasing/supplier_list.html"

    def get_queryset(self):
        return Supplier.objects.annotate(
            spent=Sum(ExpressionWrapper(
                F("purchases__items__quantity") * F("purchases__items__unit_price"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ))
        )


class SupplierCreateView(RoleRequiredMixin, AuditMixin, CreateView):
    allowed_roles = PURCHASE_ROLES
    model = Supplier
    form_class = SupplierForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("New supplier")}


class SupplierUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = PURCHASE_ROLES
    model = Supplier
    form_class = SupplierForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("Edit supplier")}


@role_required(*PURCHASE_ROLES)
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    purchases = supplier.purchases.prefetch_related("items")
    total = PurchaseItem.objects.filter(purchase__supplier=supplier).aggregate(total=Sum(LINE_TOTAL))["total"]
    unpaid = sum((p.unpaid for p in purchases), Decimal("0"))
    from .models import PurchaseReturn

    returns = list(PurchaseReturn.objects.filter(purchase__supplier=supplier).select_related("purchase")
                   .prefetch_related("lines__item"))
    credit = sum((r.refunded for r in returns if r.settlement == PurchaseReturn.Settlement.CREDIT), Decimal("0"))
    money_back = sum((r.refunded for r in returns if r.settlement == PurchaseReturn.Settlement.MONEY), Decimal("0"))
    return render(
        request, "purchasing/supplier_detail.html",
        {"supplier": supplier, "purchases": purchases, "total": total or Decimal("0"), "unpaid": unpaid,
         "returns": returns, "credit": credit, "money_back": money_back},
    )


def _place_of_list(request):
    """The place whose purchases are shown (round 15: each place has its own): ``?place=`` (a place the person buys
    for, or "all"), else the place worked in now."""
    places = purchase_places(request.user)
    chosen = request.GET.get("place", "")
    if chosen == "all" and len(places) > 1:
        return None, places
    for place in places:
        if str(place.pk) == chosen:
            return place, places
    here = branch_for_user(request.user)
    return (here if here in places else (places[0] if places else here)), places


@role_required(*PURCHASE_ROLES)
def purchase_list(request):
    form = PurchaseFilterForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today.replace(day=1), today
    place, places = _place_of_list(request)
    purchases = Purchase.objects.select_related("supplier", "created_by", "branch").prefetch_related(
        "items__category")
    items = PurchaseItem.objects.select_related("category")
    if place is not None:
        purchases, items = purchases.filter(branch=place), items.filter(purchase__branch=place)
    if form.is_valid():
        data = form.cleaned_data
        date_from = data.get("date_from") or date_from
        date_to = data.get("date_to") or date_to
        if data.get("supplier"):
            purchases = purchases.filter(supplier=data["supplier"])
            items = items.filter(purchase__supplier=data["supplier"])
        if data.get("category"):
            purchases = purchases.filter(items__category=data["category"]).distinct()
            items = items.filter(category=data["category"])
        if data.get("kind"):
            purchases = purchases.filter(items__category__kind=data["kind"]).distinct()
            items = items.filter(category__kind=data["kind"])
        if data.get("group"):
            purchases = purchases.filter(items__category__group=data["group"]).distinct()
            items = items.filter(category__group=data["group"])
    purchases = purchases.filter(purchase_date__range=(date_from, date_to))
    items = items.filter(purchase__purchase_date__range=(date_from, date_to))
    rows = items.values("category").annotate(total=Sum(LINE_TOTAL)).order_by("-total")
    categories = PurchaseCategory.objects.in_bulk([row["category"] for row in rows])
    by_category = [(categories[row["category"]], row["total"]) for row in rows]
    # Dental or not, then each group, then its categories (round 15).
    groups = dict(PurchaseCategory.Group.choices)
    kinds = {code: {"code": code, "label": label, "total": Decimal("0"), "groups": {}}
             for code, label in PurchaseCategory.Kind.choices}
    for category, amount in by_category:
        kind = kinds[category.kind]
        kind["total"] += amount
        code = category.group or ("" if category.kind == PurchaseCategory.Kind.DENTAL else "other")
        group = kind["groups"].setdefault(code, {"code": code, "label": groups.get(code, _("Not grouped")),
                                                 "total": Decimal("0"), "categories": []})
        group["total"] += amount
        group["categories"].append((category, amount))
    by_kind = [dict(kind, groups=sorted(kind["groups"].values(), key=lambda g: -g["total"]))
               for kind in kinds.values() if kind["groups"]]
    params = request.GET.copy()
    params.pop("place", None)
    return render(
        request,
        "purchasing/purchase_list.html",
        {
            "filter_form": form,
            "purchases": purchases,
            "by_category": by_category,
            "by_kind": by_kind,
            "total": items.aggregate(total=Sum(LINE_TOTAL))["total"] or Decimal("0"),
            "date_from": date_from,
            "date_to": date_to,
            "place": place, "places": places if len(places) > 1 else [], "query": params.urlencode(),
        },
    )


PRICE_RISE_WARNING = 10  # percent: a stock item bought dearer than this is told to the owner and the stock manager


def _tell_price_rises(purchase, user):
    """Round 13: a price that went up a lot since the last purchase is told at once."""
    from apps.core.models import Notification
    from apps.core.notify import notify_roles
    from apps.core.roles import OWNER, STOCK
    from apps.stock.prices import before_purchase

    changes = before_purchase(purchase)
    for line in purchase.items.select_related("stock_item"):
        before, change = changes.get(line.pk, (None, None))
        if change is not None and change >= PRICE_RISE_WARNING:
            notify_roles((OWNER, STOCK), gettext_lazy("Price up %(change)s%%: %(item)s"),
                         gettext_lazy("From %(before)s to %(price)s (%(supplier)s)."),
                         line.stock_item.get_absolute_url(), Notification.Level.WARNING, exclude=user,
                         params={"change": f"{change:g}", "item": line.stock_item.name, "before": f"{before:g}",
                                 "price": f"{line.unit_price:g}", "supplier": str(purchase.supplier)})


def _purchase_form(request, purchase=None):
    form = PurchaseForm(request.POST or None, request.FILES or None, instance=purchase, user=request.user,
                        place=branch_for_user(request.user))
    formset = PurchaseItemFormSet(request.POST or None, instance=purchase or Purchase(), prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            purchase = form.save(commit=False)
            if not purchase.pk:
                if "branch" not in form.fields:
                    purchase.branch = branch_for_user(request.user)
                purchase.created_by = request.user
            purchase.save()
            formset.instance = purchase
            formset.save()
            received = sync_purchase(purchase, request.user)
            fawry.sync(purchase)
            _tell_price_rises(purchase, request.user)
        message = _("Purchase saved. Total: %(total)s") % {"total": purchase.total}
        if received:
            message += " " + _("%(n)s items added to stock.") % {"n": received}
        messages.success(request, message)
        return redirect(purchase)
    from apps.stock.prices import last_prices

    return render(
        request, "purchasing/purchase_form.html",
        {"form": form, "formset": formset, "title": _("Edit purchase") if purchase else _("New purchase"),
         "last_prices": last_prices(None)},
    )


@role_required(*PURCHASE_ROLES)
def purchase_create(request):
    return _purchase_form(request)


@role_required(*PURCHASE_ROLES)
def purchase_update(request, pk):
    return _purchase_form(request, get_object_or_404(Purchase, pk=pk))


@role_required(*PURCHASE_ROLES)
def purchase_detail(request, pk):
    from apps.stock.prices import before_purchase

    purchase = get_object_or_404(Purchase.objects.select_related("supplier", "created_by"), pk=pk)
    changes = before_purchase(purchase)
    items = list(purchase.items.select_related("category", "stock_item"))
    for item in items:  # the price paid before this purchase, and the change
        item.before, item.change = changes.get(item.pk, (None, None))
        item.given_back = item.returned_quantity()
    return render(
        request, "purchasing/purchase_detail.html",
        {"purchase": purchase, "items": items,
         "returns": purchase.returns.prefetch_related("lines__item").order_by("-returned_on", "-pk")},
    )
