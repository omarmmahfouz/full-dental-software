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
    branch = models.ForeignKey(
        Branch, verbose_name=_("only at"), null=True, blank=True, on_delete=models.PROTECT, related_name="services",
        help_text=_("Empty = offered at every place. For a price list of one place (e.g. CIC), choose it here."))

    class Meta(LookupModel.Meta):
        verbose_name = _("paid service")
        verbose_name_plural = _("paid services")

    @classmethod
    def for_place(cls, branch):
        """The services offered at a place: its own and those of every place."""
        services = cls.objects.filter(is_active=True)
        if branch is not None:
            services = services.filter(models.Q(branch__isnull=True) | models.Q(branch=branch))
        return services


class FawryMachine(models.Model):
    """One of the owner's Fawry POS machines. Each card payment says which machine took it."""

    name = models.CharField(_("name"), max_length=60)
    terminal_id = models.CharField(_("terminal / serial number"), max_length=60, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["sort_order", "pk"]
        verbose_name = _("Fawry machine")
        verbose_name_plural = _("Fawry machines")

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        return cls.objects.filter(is_active=True).first()


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
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.PROTECT,
                               related_name="bills")
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
        if self.branch_id is None:
            self.branch_id = self.patient.branch_id  # the views give the place worked in; this is the fallback
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
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.PROTECT,
                               related_name="charges")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("dentist who did the work"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="charges",
                                help_text=_("Counts for the doctor's share at clinics that pay a percentage."))
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

    def save(self, *args, **kwargs):
        if self.bill_id is not None:
            if self.branch_id is None:
                self.branch_id = self.bill.branch_id
            if self.dentist_id is None:
                self.dentist_id = self.bill.dentist_id
        if self.branch_id is None:
            self.branch_id = self.patient.branch_id
        super().save(*args, **kwargs)

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
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.PROTECT,
                               related_name="patient_payments")
    fawry_machine = models.ForeignKey(FawryMachine, verbose_name=_("Fawry machine"), null=True, blank=True,
                                      on_delete=models.PROTECT, related_name="patient_payments",
                                      help_text=_("For card payments: the machine that took it."))

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = _("patient payment")
        verbose_name_plural = _("patient payments")

    def __str__(self):
        return f"{self.receipt_number} - {self.amount}"

    def get_absolute_url(self):
        return reverse("billing:receipt", args=[self.pk])

    def save(self, *args, **kwargs):
        if self.branch_id is None:
            source = self.bill or self.charge
            self.branch_id = source.branch_id if source is not None else self.patient.branch_id
        if self.method == PaymentMethod.FAWRY and self.fawry_machine_id is None:
            self.fawry_machine = FawryMachine.default()
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
                source=Bill.Source.RECEPTION, notes="", branch=None):
    """A bill with one service given per line: {"service", "teeth", "price", "discount_percent",
    "discount_reason"}. An empty price takes the service's price. The bill is for ``branch`` (the place
    worked in; else the visit's place, else the patient's)."""
    billed_on = billed_on or timezone.localdate()
    branch = branch or (appointment.branch if appointment is not None else None) or patient.branch
    with transaction.atomic():
        bill = Bill.objects.create(patient=patient, billed_on=billed_on, appointment=appointment, dentist=dentist,
                                   source=source, notes=notes, created_by=user, branch=branch)
        for line in lines:
            service = line["service"]
            price = line.get("price")
            Charge.objects.create(
                patient=patient, bill=bill, service=service, teeth=line.get("teeth", ""), charged_on=billed_on,
                branch=branch, dentist=line.get("dentist") or dentist,
                price=service.price if price is None else price, discount_percent=line.get("discount_percent") or 0,
                discount_reason=line.get("discount_reason", ""), created_by=user,
            )
    return bill


class FawryMove(TimeStampedModel):
    """One move of money through one of the Fawry POS machines, for the academy, the private clinic or CIC.

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
    machine = models.ForeignKey(FawryMachine, verbose_name=_("Fawry machine"), null=True, blank=True,
                                on_delete=models.PROTECT, related_name="moves")
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
        if self.machine_id is None:
            self.machine = FawryMachine.default()
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"FW-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def source(self):
        return self.patient_payment or self.academy_payment or self.purchase

    @property
    def source_label(self):
        """The receipt number and the description, as shown in the Fawry ledger."""
        source = self.source
        if source is None or self.purchase_id:
            return self.description
        return f"{source.receipt_number} — {self.description}"

    @property
    def is_automatic(self):
        return bool(self.patient_payment_id or self.academy_payment_id or self.purchase_id)

    @property
    def balance_change(self):
        """What the move adds to (or takes from) the money held at Fawry."""
        if self.kind in self.MONEY_IN:
            return self.amount - self.fee
        return -(self.amount + self.fee)
