"""How the doctors of a clinic (e.g. CIC, the Cairo Implant Center) are paid, and what they were paid.

A doctor gets a percentage of what the patient paid, a fixed amount for each service (for each tooth),
or a fixed amount for each visit. The clinic manager (moderator) or the owner sets this per doctor and
per place, and can set one service apart (e.g. implants at a fixed amount, the rest at a percentage)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.models import Branch, TimeStampedModel


class FeeRule(TimeStampedModel):
    class Method(models.TextChoices):
        PERCENT = "percent", _("Percentage of what the patient paid")
        PER_UNIT = "per_unit", _("Fixed amount for each service (each tooth)")
        PER_VISIT = "per_visit", _("Fixed amount for each visit")

    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("doctor"), on_delete=models.CASCADE,
                                related_name="fee_rules")
    branch = models.ForeignKey(Branch, verbose_name=_("place"), on_delete=models.PROTECT, related_name="fee_rules")
    service = models.ForeignKey(
        "billing.Service", verbose_name=_("for the service"), null=True, blank=True, on_delete=models.PROTECT,
        related_name="fee_rules",
        help_text=_("Empty = every service. A rule for one service (e.g. implants) comes before the rule for "
                    "every service."))
    method = models.CharField(_("how the doctor is paid"), max_length=12, choices=Method.choices,
                              default=Method.PERCENT)
    value = models.DecimalField(_("percentage or amount"), max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(0)],
                                help_text=_("e.g. 30 for 30%, or 1500 for 1,500 a tooth or a visit."))
    starts_on = models.DateField(_("from"), default=timezone.localdate)
    ends_on = models.DateField(_("until"), null=True, blank=True, help_text=_("Empty = until changed."))
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["branch", "dentist__full_name", "service", "-starts_on"]
        verbose_name = _("doctor's fee rule")
        verbose_name_plural = _("doctors' fee rules")

    def __str__(self):
        return f"{self.dentist} — {self.branch.code}: {self.describe}"

    @property
    def describe(self):
        if self.method == self.Method.PERCENT:
            text = _("%(value)s%% of what was paid") % {"value": f"{self.value:g}"}
        elif self.method == self.Method.PER_UNIT:
            text = _("%(value)s for each service / tooth") % {"value": f"{self.value:,.0f}"}
        else:
            text = _("%(value)s for each visit") % {"value": f"{self.value:,.0f}"}
        return f"{self.service}: {text}" if self.service_id else str(text)

    def applies_on(self, day):
        return self.is_active and self.starts_on <= day and (self.ends_on is None or self.ends_on >= day)

    def clean(self):
        if self.method == self.Method.PERCENT and self.value is not None and self.value > 100:
            raise ValidationError({"value": _("A percentage cannot be more than 100.")})
        if self.method == self.Method.PER_VISIT and self.service_id:
            raise ValidationError({"service": _("An amount for each visit is for every service: leave the service "
                                                "empty.")})
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": _("The end is before the start.")})


class DoctorPayout(TimeStampedModel):
    """Money paid to a doctor for their work at a place."""

    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("doctor"), on_delete=models.PROTECT,
                                related_name="payouts")
    branch = models.ForeignKey(Branch, verbose_name=_("place"), on_delete=models.PROTECT, related_name="payouts")
    paid_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    amount = models.DecimalField(_("amount paid"), max_digits=12, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(_("payment method"), max_length=20, choices=PaymentMethod.choices,
                              default=PaymentMethod.CASH)
    reference = models.CharField(_("transaction reference"), max_length=100, blank=True)
    period_from = models.DateField(_("for the work from"), null=True, blank=True)
    period_to = models.DateField(_("to"), null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = _("payment to a doctor")
        verbose_name_plural = _("payments to doctors")

    def __str__(self):
        return f"{self.dentist} — {self.amount}"

    def get_absolute_url(self):
        return reverse("clinics:statement", args=[self.dentist_id]) + f"?place={self.branch.code}"
