"""What a patient pays the academy for: services from a price list (CBCT, consultation...),
with a discount of up to 100%, paid at once or in parts."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.models import Branch, LookupModel, TimeStampedModel


class Service(LookupModel):
    """A paid service and its usual price (the owner keeps the list in Settings)."""

    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2, default=0,
                                validators=[MinValueValidator(0)])
    quick_button = models.BooleanField(
        _("quick button on a new bill"), default=False,
        help_text=_("Shown as a one-click button on a new bill, e.g. first-visit examination and CBCT."))

    class Meta(LookupModel.Meta):
        verbose_name = _("paid service")
        verbose_name_plural = _("paid services")


class Bill(TimeStampedModel):
    """One bill: the services given to a patient at one visit, printed for the patient.
    The reception makes it, or the dentist adds it when recording the treatment."""

    class Source(models.TextChoices):
        RECEPTION = "reception", _("Reception")
        DENTIST = "dentist", _("Dentist (after the treatment)")

    number = models.CharField(_("bill number"), max_length=20, unique=True, blank=True, editable=False)
    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="bills")
    billed_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    appointment = models.ForeignKey("scheduling.Appointment", verbose_name=_("visit"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="bills")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("dentist"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="bills")
    source = models.CharField(_("made by"), max_length=10, choices=Source.choices, default=Source.RECEPTION)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-billed_on", "-pk"]
        verbose_name = _("bill")
        verbose_name_plural = _("bills")

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("billing:bill", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"BL-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    def totals(self, current=None):
        """Price, discount, net, paid and left of this bill's services (paid as the account shares it)."""
        current = current or account(self.patient)
        rows = [row for row in current["rows"] if row["charge"].bill_id == self.pk]
        return {
            "rows": rows,
            "price": sum((r["charge"].price for r in rows), Decimal("0")),
            "discount": sum((r["charge"].discount_amount for r in rows), Decimal("0")),
            "net": sum((r["charge"].net for r in rows), Decimal("0")),
            "paid": sum((r["paid"] for r in rows), Decimal("0")),
            "left": sum((r["left"] for r in rows), Decimal("0")),
        }


class Charge(TimeStampedModel):
    """A service given to a patient: its price, the discount, and what is left to pay."""

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="charges")
    bill = models.ForeignKey(Bill, verbose_name=_("bill"), null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="charges")
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
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
    bill = models.ForeignKey(Bill, verbose_name=_("bill"), null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="payments")
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
    for a service pays that service, one made for a bill pays that bill's services; other
    payments pay the oldest unpaid services first."""
    charges = list(patient.charges.select_related("service").order_by("charged_on", "pk"))
    payments = list(patient.patient_payments.order_by("paid_on", "pk"))
    paid = {charge.pk: Decimal("0") for charge in charges}
    nets = {charge.pk: charge.net for charge in charges}
    free = Decimal("0")
    for payment in payments:
        if payment.charge_id in paid:
            targets = [payment.charge_id]
        elif payment.bill_id:
            targets = [c.pk for c in charges if c.bill_id == payment.bill_id]
        else:
            targets = []
        left = payment.amount
        for pk in targets:
            take = min(left, nets[pk] - paid[pk])
            paid[pk] += take
            left -= take
        free += left
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


def create_bill(patient, lines, user, billed_on=None, appointment=None, dentist=None,
                source=Bill.Source.RECEPTION, notes=""):
    """A bill with one service given per line: {"service", "teeth", "price", "discount_percent",
    "discount_reason"}. An empty price takes the service's price."""
    billed_on = billed_on or timezone.localdate()
    with transaction.atomic():
        bill = Bill.objects.create(patient=patient, billed_on=billed_on, appointment=appointment, dentist=dentist,
                                   source=source, notes=notes, created_by=user)
        for line in lines:
            service = line["service"]
            price = line.get("price")
            Charge.objects.create(
                patient=patient, bill=bill, service=service, teeth=line.get("teeth", ""), charged_on=billed_on,
                price=service.price if price is None else price, discount_percent=line.get("discount_percent") or 0,
                discount_reason=line.get("discount_reason", ""), created_by=user,
            )
    return bill


class FawryMove(TimeStampedModel):
    """One move of money through the Fawry POS machine, for the academy, the private clinic or CIC.

    Card payments taken on the machine are added by themselves from the patient and course payments
    (and a purchase paid with Fawry becomes a bill paid through the machine); the rest is written
    by the reception. Fawry keeps a percentage of what is collected (``fee``)."""

    class Kind(models.TextChoices):
        COLLECTION = "collection", _("Card payment taken on the machine")
        SERVICE = "service", _("Bill paid through the machine")
        TOP_UP = "top_up", _("Money put on the machine")
        SETTLEMENT = "settlement", _("Fawry transferred to the bank")
        CHARGE = "charge", _("Other Fawry charge (rent, fees)")

    class Service(models.TextChoices):
        MOBILE = "mobile", _("Mobile recharge / bill")
        ELECTRICITY = "electricity", _("Electricity")
        WATER = "water", _("Water")
        GAS = "gas", _("Gas")
        INTERNET = "internet", _("Internet / landline")
        SUPPLIER = "supplier", _("Supplier (purchase)")
        OTHER = "other", _("Other")

    MONEY_IN = (Kind.COLLECTION, Kind.TOP_UP)

    number = models.CharField(_("number"), max_length=20, unique=True, blank=True, editable=False)
    branch = models.ForeignKey(Branch, verbose_name=_("for"), on_delete=models.PROTECT, related_name="fawry_moves",
                               help_text=_("The academy, the private clinic or CIC."))
    kind = models.CharField(_("move"), max_length=20, choices=Kind.choices, default=Kind.COLLECTION)
    moved_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2,
                                 validators=[MinValueValidator(Decimal("0.01"))])
    fee = models.DecimalField(_("Fawry fee"), max_digits=10, decimal_places=2, default=0,
                              validators=[MinValueValidator(0)],
                              help_text=_("What Fawry kept. Leave empty on a card payment to use the percentage in Settings."))
    service = models.CharField(_("bill paid"), max_length=20, choices=Service.choices, blank=True)
    cash_received = models.DecimalField(
        _("cash taken for it"), max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text=_("When you paid someone else's bill (mobile, electricity...) and took cash from him."))
    reference = models.CharField(_("transaction reference"), max_length=100, blank=True)
    description = models.CharField(_("details"), max_length=255, blank=True)
    patient_payment = models.OneToOneField(PatientPayment, null=True, blank=True, on_delete=models.CASCADE,
                                           related_name="fawry_move", editable=False)
    academy_payment = models.OneToOneField("academy.Payment", null=True, blank=True, on_delete=models.CASCADE,
                                           related_name="fawry_move", editable=False)
    purchase = models.OneToOneField("purchasing.Purchase", null=True, blank=True, on_delete=models.CASCADE,
                                    related_name="fawry_move", editable=False)

    class Meta:
        ordering = ["-moved_on", "-pk"]
        verbose_name = _("Fawry move")
        verbose_name_plural = _("Fawry moves")

    def __str__(self):
        return f"{self.number} - {self.get_kind_display()} - {self.amount}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"FW-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def source(self):
        return self.patient_payment or self.academy_payment or self.purchase

    @property
    def is_automatic(self):
        return bool(self.patient_payment_id or self.academy_payment_id or self.purchase_id)

    @property
    def balance_change(self):
        """What the move adds to (or takes from) the money held at Fawry."""
        if self.kind in self.MONEY_IN:
            return self.amount - self.fee
        return -(self.amount + self.fee)
