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

    class Meta:
        verbose_name = _("purchase item")
        verbose_name_plural = _("purchase items")

    def __str__(self):
        return self.description

    @property
    def total(self):
        return (self.quantity or 0) * (self.unit_price or 0)
