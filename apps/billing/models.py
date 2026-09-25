"""What a patient pays the academy for: services from a price list (CBCT, consultation...),
with a discount of up to 100%, paid at once or in parts."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.models import LookupModel, TimeStampedModel


class Service(LookupModel):
    """A paid service and its usual price (the owner keeps the list in Settings)."""

    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2, default=0,
                                validators=[MinValueValidator(0)])

    class Meta(LookupModel.Meta):
        verbose_name = _("paid service")
        verbose_name_plural = _("paid services")


class Charge(TimeStampedModel):
    """A service given to a patient: its price, the discount, and what is left to pay."""

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="charges")
    service = models.ForeignKey(Service, verbose_name=_("service"), on_delete=models.PROTECT, related_name="charges")
    charged_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    discount_percent = models.DecimalField(
        _("discount %"), max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)], help_text=_("0 to 100 (100 = free)."))
    discount_reason = models.CharField(_("why the discount"), max_length=200, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["charged_on", "pk"]
        verbose_name = _("service given")
        verbose_name_plural = _("services given")

    def __str__(self):
        return f"{self.service} — {self.charged_on:%d/%m/%Y}"

    @property
    def discount_amount(self):
        return (self.price * self.discount_percent / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def net(self):
        return self.price - self.discount_amount


class PatientPayment(TimeStampedModel):
    receipt_number = models.CharField(_("receipt number"), max_length=20, unique=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="patient_payments")
    charge = models.ForeignKey(Charge, verbose_name=_("for"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="payments",
                               help_text=_("Leave empty to pay the oldest unpaid services first."))
    amount = models.DecimalField(_("amount paid"), max_digits=10, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    paid_on = models.DateField(_("payment date"), default=timezone.localdate, db_index=True)
    method = models.CharField(_("payment method"), max_length=20, choices=PaymentMethod.choices,
                              default=PaymentMethod.CASH)
    reference = models.CharField(_("transaction reference"), max_length=100, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = _("patient payment")
        verbose_name_plural = _("patient payments")

    def __str__(self):
        return f"{self.receipt_number} - {self.amount}"

    def get_absolute_url(self):
        return reverse("billing:receipt", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.receipt_number:
                self.receipt_number = f"PR-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(receipt_number=self.receipt_number)


def account(patient):
    """The patient's services with what is paid and left on each, and the totals. A payment made
    for a service pays that service; other payments pay the oldest unpaid services first."""
    charges = list(patient.charges.select_related("service").order_by("charged_on", "pk"))
    payments = list(patient.patient_payments.order_by("paid_on", "pk"))
    paid = {charge.pk: Decimal("0") for charge in charges}
    nets = {charge.pk: charge.net for charge in charges}
    free = Decimal("0")
    for payment in payments:
        if payment.charge_id in paid:
            take = min(payment.amount, nets[payment.charge_id] - paid[payment.charge_id])
            paid[payment.charge_id] += take
            free += payment.amount - take
        else:
            free += payment.amount
    for charge in charges:
        take = min(free, nets[charge.pk] - paid[charge.pk])
        paid[charge.pk] += take
        free -= take
    rows = [{"charge": c, "paid": paid[c.pk], "left": nets[c.pk] - paid[c.pk]} for c in charges]
    total_net = sum(nets.values(), Decimal("0"))
    total_paid = sum((p.amount for p in payments), Decimal("0"))
    return {
        "rows": rows, "payments": payments,
        "price": sum((c.price for c in charges), Decimal("0")),
        "discount": sum((c.discount_amount for c in charges), Decimal("0")),
        "net": total_net, "paid": total_paid, "balance": total_net - total_paid,
    }
