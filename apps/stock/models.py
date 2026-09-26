from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import LookupModel, TimeStampedModel


class StockCategory(LookupModel):
    """Dental materials, instruments, implants, consumables, food & beverage..."""

    class Meta(LookupModel.Meta):
        verbose_name = _("stock category")
        verbose_name_plural = _("stock categories")


class StockItem(TimeStampedModel):
    name = models.CharField(_("item"), max_length=150, db_index=True)
    category = models.ForeignKey(StockCategory, verbose_name=_("category"), on_delete=models.PROTECT, related_name="items")
    unit = models.CharField(_("unit"), max_length=30, blank=True, help_text=_("piece, box, carpule, pack..."))
    quantity = models.DecimalField(_("in stock"), max_digits=10, decimal_places=2, default=0, editable=False)
    min_quantity = models.DecimalField(
        _("reorder level"), max_digits=10, decimal_places=2, default=0,
        help_text=_("The stock manager is warned when the quantity falls to this number or below."),
    )
    location = models.CharField(_("place"), max_length=100, blank=True, help_text=_("e.g. store, room 2, sterilisation"))
    code = models.CharField(_("code / barcode"), max_length=60, blank=True)
    unit_cost = models.DecimalField(_("last unit price"), max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(_("in use"), default=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    implant_system = models.ForeignKey(
        "surgery.ImplantSystem", verbose_name=_("implant company / type"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="stock_items",
        help_text=_("For implants only: the surgery chart then takes them out of stock by lot."))
    implant_diameter = models.DecimalField(_("implant diameter (mm)"), max_digits=3, decimal_places=1, null=True, blank=True)
    implant_length = models.DecimalField(_("implant length (mm)"), max_digits=3, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ["category__sort_order", "name"]
        verbose_name = _("stock item")
        verbose_name_plural = _("stock items")

    def __str__(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name

    def get_absolute_url(self):
        return reverse("stock:item_detail", args=[self.pk])

    @property
    def is_low(self):
        return self.quantity <= 0 or (self.min_quantity > 0 and self.quantity <= self.min_quantity)

    @property
    def is_implant(self):
        return bool(self.implant_system_id and self.implant_diameter and self.implant_length)

    def lots(self):
        """What is left of each lot (from the movements that name a lot); '' = received without a lot number."""
        from django.db.models import Max, Sum

        rows = {row["lot"]: row for row in self.movements.exclude(lot="").values("lot").annotate(
            left=Sum("change"), expiry=Max("expiry_date"))}
        result = [{"lot": lot, "left": row["left"], "expiry": row["expiry"]}
                  for lot, row in sorted(rows.items(), key=lambda r: (r[1]["expiry"] is None, r[1]["expiry"], r[0]))
                  if row["left"] > 0]
        without = self.quantity - sum((row["left"] for row in rows.values()), 0)
        if without > 0:
            result.append({"lot": "", "left": without, "expiry": None})
        return result

    @property
    def value(self):
        return (self.quantity * self.unit_cost) if self.unit_cost is not None else None


class StockMovement(models.Model):
    """Every change of stock: received, used, damaged / expired, or corrected after counting."""

    class Kind(models.TextChoices):
        IN = "in", _("Received into stock")
        OUT = "out", _("Taken out / used")
        WASTE = "waste", _("Damaged / expired")
        COUNT = "count", _("Stock count (correct the quantity)")

    item = models.ForeignKey(StockItem, verbose_name=_("item"), on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(_("movement"), max_length=10, choices=Kind.choices)
    quantity = models.DecimalField(
        _("quantity"), max_digits=10, decimal_places=2,
        help_text=_("For a stock count, write the quantity you counted."),
    )
    change = models.DecimalField(_("change"), max_digits=10, decimal_places=2, editable=False)
    moved_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    destination = models.CharField(_("for / taken by"), max_length=150, blank=True,
                                   help_text=_("e.g. room 3, Dr. Mona, sterilisation, kitchen"))
    lot = models.CharField(_("lot"), max_length=60, blank=True)
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)
    unit_cost = models.DecimalField(_("unit price"), max_digits=12, decimal_places=2, null=True, blank=True)
    purchase_item = models.OneToOneField(
        "purchasing.PurchaseItem", null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movement"
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("recorded by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-moved_at", "-pk"]
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")

    def __str__(self):
        return f"{self.item} {self.change:+g}"

