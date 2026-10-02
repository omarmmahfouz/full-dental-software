import os
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.models import Branch, LookupModel, TimeStampedModel


class Supplier(TimeStampedModel):
    name = models.CharField(_("company / shop name"), max_length=150, unique=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    contact_person = models.CharField(_("contact person"), max_length=100, blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("purchasing:supplier_detail", args=[self.pk])


class PurchaseCategory(LookupModel):
    class Kind(models.TextChoices):
        DENTAL = "dental", _("Dental")
        NON_DENTAL = "non_dental", _("Non-dental")

    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)

    class Meta(LookupModel.Meta):
        ordering = ["kind", "sort_order", "name_ar"]
        verbose_name = _("purchase category")
        verbose_name_plural = _("purchase categories")


def invoice_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"purchases/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{ext}"


class Purchase(TimeStampedModel):
    class PaymentStatus(models.TextChoices):
        PAID = "paid", _("Paid")
        PARTIAL = "partial", _("Partly paid")
        CREDIT = "credit", _("On credit (not paid)")

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="purchases")
    supplier = models.ForeignKey(
        Supplier, verbose_name=_("supplier"), on_delete=models.PROTECT, related_name="purchases"
    )
    purchase_date = models.DateField(_("purchase date"), default=timezone.localdate, db_index=True)
    invoice_number = models.CharField(_("supplier invoice no."), max_length=50, blank=True)
    payment_method = models.CharField(
        _("payment method"), max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        _("payment status"), max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PAID
    )
    amount_paid = models.DecimalField(
        _("amount paid"), max_digits=12, decimal_places=2, null=True, blank=True,
        help_text=_("Leave empty when the full invoice is paid."),
    )
    invoice_image = models.FileField(_("invoice photo"), upload_to=invoice_path, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["-purchase_date", "-pk"]
        verbose_name = _("purchase")
        verbose_name_plural = _("purchases")

    def __str__(self):
        return f"{self.supplier} - {self.purchase_date}"

    def get_absolute_url(self):
        return reverse("purchasing:purchase_detail", args=[self.pk])

    @property
    def total(self):
        return sum((item.total for item in self.items.all()), Decimal("0"))

    @property
    def paid(self):
        if self.payment_status == self.PaymentStatus.PAID:
            return self.total
        return self.amount_paid or Decimal("0")

    @property
    def unpaid(self):
        return self.total - self.paid

    @property
    def refunded(self):
        """Money or credit that came back for items given back (purchase returns, step 3)."""
        return sum((r.refunded for r in self.returns.all()), Decimal("0"))


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    category = models.ForeignKey(PurchaseCategory, verbose_name=_("category"), on_delete=models.PROTECT)
    description = models.CharField(_("item"), max_length=200)
    quantity = models.DecimalField(
        _("quantity"), max_digits=10, decimal_places=2, default=1, validators=[MinValueValidator(Decimal("0.01"))]
    )
    unit = models.CharField(_("unit"), max_length=30, blank=True, help_text=_("piece, box, kg..."))
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    stock_item = models.ForeignKey(
        "stock.StockItem", verbose_name=_("add to stock item"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="purchase_lines",
    )

    class Meta:
        verbose_name = _("purchase item")
        verbose_name_plural = _("purchase items")

    def __str__(self):
        return self.description

    @property
    def total(self):
        return (self.quantity or 0) * (self.unit_price or 0)

    def returned_quantity(self, exclude=None):
        """How many of this line were given back (returns not cancelled)."""
        lines = self.returned.exclude(purchase_return__status=PurchaseReturn.Status.CANCELLED)
        if exclude is not None:
            lines = lines.exclude(purchase_return=exclude)
        return lines.aggregate(total=models.Sum("quantity"))["total"] or Decimal("0")


class PurchaseReturn(TimeStampedModel):
    """Items given back to the supplier (round 13), in three steps: 1. written here (what, how many, why): the
    stock items go out of the stock at once; 2. the supplier takes them; 3. the money comes back, or a credit with
    the supplier, or new items instead (they come into the stock again). A return is never deleted: it is cancelled."""

    class Reason(models.TextChoices):
        DAMAGED = "damaged", _("Damaged or broken")
        EXPIRED = "expired", _("Expired or near expiry")
        WRONG = "wrong", _("Wrong item or size")
        EXTRA = "extra", _("More than we need")
        QUALITY = "quality", _("Bad quality")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        WAITING = "waiting", _("1. Waiting for the supplier to take them")
        TAKEN = "taken", _("2. Taken by the supplier: waiting for the refund")
        DONE = "done", _("3. Done")
        CANCELLED = "cancelled", _("Cancelled")

    class Settlement(models.TextChoices):
        MONEY = "money", _("Money given back")
        CREDIT = "credit", _("Credit with the supplier (off the next invoice)")
        REPLACED = "replaced", _("New items instead (no money)")

    purchase = models.ForeignKey(Purchase, verbose_name=_("purchase"), on_delete=models.PROTECT,
                                 related_name="returns")
    returned_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    reason = models.CharField(_("why"), max_length=20, choices=Reason.choices)
    notes = models.CharField(_("details"), max_length=255, blank=True)
    status = models.CharField(_("step"), max_length=20, choices=Status.choices, default=Status.WAITING)
    taken_on = models.DateField(_("taken by the supplier on"), null=True, blank=True)
    taken_by = models.CharField(_("taken by (the supplier's person)"), max_length=100, blank=True)
    settlement = models.CharField(_("refund"), max_length=20, choices=Settlement.choices, blank=True)
    amount = models.DecimalField(_("amount given back"), max_digits=12, decimal_places=2, null=True, blank=True,
                                 help_text=_("Money or credit. Empty = the value of the items given back."))
    method = models.CharField(_("how the money came back"), max_length=20, choices=PaymentMethod.choices,
                              blank=True)
    settled_on = models.DateField(_("refunded on"), null=True, blank=True)
    cancel_reason = models.CharField(_("why cancelled"), max_length=255, blank=True)

    class Meta:
        ordering = ["-returned_on", "-pk"]
        verbose_name = _("purchase return")
        verbose_name_plural = _("purchase returns")

    def __str__(self):
        return f"{_('Return')} {self.pk} — {self.purchase}"

    def get_absolute_url(self):
        return reverse("purchasing:return_detail", args=[self.pk])

    @property
    def value(self):
        """What the items given back cost on the invoice."""
        return sum((line.total for line in self.lines.all()), Decimal("0")).quantize(Decimal("0.01"))

    @property
    def refunded(self):
        """The money or credit that came back (0 until step 3, and for items replaced)."""
        if self.status != self.Status.DONE or self.settlement == self.Settlement.REPLACED:
            return Decimal("0")
        return self.amount if self.amount is not None else self.value


class PurchaseReturnLine(models.Model):
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(PurchaseItem, verbose_name=_("item"), on_delete=models.PROTECT, related_name="returned")
    quantity = models.DecimalField(_("quantity given back"), max_digits=10, decimal_places=2,
                                   validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        verbose_name = _("item given back")
        verbose_name_plural = _("items given back")

    @property
    def total(self):
        return self.quantity * self.item.unit_price
