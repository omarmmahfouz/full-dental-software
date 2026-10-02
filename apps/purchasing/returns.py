"""Giving bought items back to the supplier (round 13), step by step (see ``PurchaseReturn``):
1. ``return_create``: what goes back and why; the stock items go out of the stock;
2. ``return_taken``: the supplier took them;
3. ``return_settle``: the money or a credit came back, or new items came instead (into the stock again).
A return written by mistake is cancelled (the items come back into the stock), never deleted."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.roles import PURCHASE_ROLES
from apps.stock.models import StockMovement
from apps.stock.services import record_movement

from .forms import ReturnForm, ReturnSettleForm, ReturnTakenForm
from .models import Purchase, PurchaseReturn, PurchaseReturnLine


def _stock(purchase_return, kind, user, note):
    """Move the stock items of a return out (given back) or in (cancelled, or new items instead)."""
    for line in purchase_return.lines.select_related("item__stock_item"):
        if line.item.stock_item_id:
            record_movement(line.item.stock_item, kind, line.quantity, user, branch=purchase_return.purchase.branch,
                            notes=f"{note} #{purchase_return.pk} — {purchase_return.purchase.supplier}"[:255])


@role_required(*PURCHASE_ROLES)
def return_create(request, purchase_pk):
    purchase = get_object_or_404(Purchase.objects.select_related("supplier"), pk=purchase_pk)
    form = ReturnForm(request.POST or None, purchase=purchase)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            purchase_return = form.save(commit=False)
            purchase_return.purchase = purchase
            purchase_return.created_by = request.user
            purchase_return.save()
            for line, quantity in form.chosen:
                PurchaseReturnLine.objects.create(purchase_return=purchase_return, item=line, quantity=quantity)
            _stock(purchase_return, StockMovement.Kind.RETURN, request.user, _("Given back"))
        messages.success(request, _("Written. The items given back went out of the stock. Next: when the supplier "
                                    "takes them, press “The supplier took them”."))
        return redirect(purchase_return)
    return render(request, "purchasing/return_form.html", {"form": form, "purchase": purchase})


@role_required(*PURCHASE_ROLES)
def return_detail(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn.objects.select_related("purchase__supplier", "created_by"),
                                        pk=pk)
    return render(request, "purchasing/return_detail.html", {
        "ret": purchase_return, "lines": purchase_return.lines.select_related("item__stock_item"),
        "taken_form": ReturnTakenForm(instance=purchase_return, prefix="t"),
        "settle_form": ReturnSettleForm(instance=purchase_return, prefix="s"),
    })


@role_required(*PURCHASE_ROLES)
@require_POST
def return_taken(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk, status=PurchaseReturn.Status.WAITING)
    form = ReturnTakenForm(request.POST, instance=purchase_return, prefix="t")
    if form.is_valid():
        purchase_return = form.save(commit=False)
        purchase_return.status = PurchaseReturn.Status.TAKEN
        purchase_return.save()
        messages.success(request, _("Step 2 done. When the money, the credit or the new items come, finish step 3."))
        return redirect(purchase_return)
    return render(request, "purchasing/return_detail.html", {
        "ret": purchase_return, "lines": purchase_return.lines.select_related("item__stock_item"),
        "taken_form": form, "settle_form": ReturnSettleForm(instance=purchase_return, prefix="s")})


@role_required(*PURCHASE_ROLES)
@require_POST
def return_settle(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk, status__in=(
        PurchaseReturn.Status.WAITING, PurchaseReturn.Status.TAKEN))
    form = ReturnSettleForm(request.POST, instance=purchase_return, prefix="s")
    if form.is_valid():
        with transaction.atomic():
            purchase_return = form.save(commit=False)
            if purchase_return.taken_on is None:
                purchase_return.taken_on = purchase_return.settled_on
            purchase_return.status = PurchaseReturn.Status.DONE
            purchase_return.save()
            if purchase_return.settlement == PurchaseReturn.Settlement.REPLACED:
                _stock(purchase_return, StockMovement.Kind.IN, request.user, _("New items instead of the return"))
        messages.success(request, _("The return is finished."))
        return redirect(purchase_return)
    return render(request, "purchasing/return_detail.html", {
        "ret": purchase_return, "lines": purchase_return.lines.select_related("item__stock_item"),
        "taken_form": ReturnTakenForm(instance=purchase_return, prefix="t"), "settle_form": form})


@role_required(*PURCHASE_ROLES)
@require_POST
def return_cancel(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if purchase_return.status == PurchaseReturn.Status.CANCELLED or not reason:
        messages.error(request, _("Write why the return is cancelled."))
        return redirect(purchase_return)
    with transaction.atomic():
        if purchase_return.settlement != PurchaseReturn.Settlement.REPLACED:
            _stock(purchase_return, StockMovement.Kind.IN, request.user, _("Return cancelled"))
        purchase_return.status = PurchaseReturn.Status.CANCELLED
        purchase_return.cancel_reason = reason[:255]
        purchase_return.save(update_fields=["status", "cancel_reason", "updated_at"])
    messages.warning(request, _("The return was cancelled and its items are back in the stock."))
    return redirect(purchase_return)


@role_required(*PURCHASE_ROLES)
def return_list(request):
    """Every return: the open ones first (waiting for the supplier, or for the refund)."""
    returns = PurchaseReturn.objects.select_related("purchase__supplier").prefetch_related("lines__item")
    order = {PurchaseReturn.Status.WAITING: 0, PurchaseReturn.Status.TAKEN: 1}
    rows = sorted(returns[:300], key=lambda r: (order.get(r.status, 2), -r.returned_on.toordinal(), -r.pk))
    return render(request, "purchasing/return_list.html", {"returns": rows, "today": timezone.localdate()})
