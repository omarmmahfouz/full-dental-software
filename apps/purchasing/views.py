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

from .forms import PurchaseFilterForm, PurchaseForm, PurchaseItemFormSet, SupplierForm
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
    return render(
        request, "purchasing/supplier_detail.html",
        {"supplier": supplier, "purchases": purchases, "total": total or Decimal("0"), "unpaid": unpaid},
    )


@role_required(*PURCHASE_ROLES)
def purchase_list(request):
    form = PurchaseFilterForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today.replace(day=1), today
    purchases = Purchase.objects.select_related("supplier", "created_by").prefetch_related("items__category")
    items = PurchaseItem.objects.select_related("category")
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
    purchases = purchases.filter(purchase_date__range=(date_from, date_to))
    items = items.filter(purchase__purchase_date__range=(date_from, date_to))
    rows = items.values("category").annotate(total=Sum(LINE_TOTAL)).order_by("-total")
    categories = PurchaseCategory.objects.in_bulk([row["category"] for row in rows])
    by_category = [(categories[row["category"]], row["total"]) for row in rows]
    return render(
        request,
        "purchasing/purchase_list.html",
        {
            "filter_form": form,
            "purchases": purchases,
            "by_category": by_category,
            "total": items.aggregate(total=Sum(LINE_TOTAL))["total"] or Decimal("0"),
            "date_from": date_from,
            "date_to": date_to,
        },
    )


def _purchase_form(request, purchase=None):
    form = PurchaseForm(request.POST or None, request.FILES or None, instance=purchase)
    formset = PurchaseItemFormSet(request.POST or None, instance=purchase or Purchase(), prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            purchase = form.save(commit=False)
            if not purchase.pk:
                purchase.branch = branch_for_user(request.user)
                purchase.created_by = request.user
            purchase.save()
            formset.instance = purchase
            formset.save()
            received = sync_purchase(purchase, request.user)
            fawry.sync(purchase)
        message = _("Purchase saved. Total: %(total)s") % {"total": purchase.total}
        if received:
            message += " " + _("%(n)s items added to stock.") % {"n": received}
        messages.success(request, message)
        return redirect(purchase)
    return render(
        request, "purchasing/purchase_form.html",
        {"form": form, "formset": formset, "title": _("Edit purchase") if purchase else _("New purchase")},
    )


@role_required(*PURCHASE_ROLES)
def purchase_create(request):
    return _purchase_form(request)


@role_required(*PURCHASE_ROLES)
def purchase_update(request, pk):
    return _purchase_form(request, get_object_or_404(Purchase, pk=pk))


@role_required(*PURCHASE_ROLES)
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase.objects.select_related("supplier", "created_by"), pk=pk)
    return render(
        request, "purchasing/purchase_detail.html",
        {"purchase": purchase, "items": purchase.items.select_related("category")},
    )
