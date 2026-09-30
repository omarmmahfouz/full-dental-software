"""The dental lab: the work received from our places (CIA, CIC, El Khadem) and from outside clinics, each client with
its own prices; every case goes through its steps (design, milling, sintering...), each step with the person who did it
and the time it took; remakes, work sent to another lab, the blocks and what was made from each, the receipts, and the
WhatsApp answers to the doctors."""

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.clinical.models import LabCategory, LabRequest
from apps.core.models import Branch, TimeStampedModel


class Step(models.TextChoices):
    """Where a case is. The work steps are in their usual order; the last ones are off the usual road."""

    INCOMING = "incoming", _("On the way to the lab")
    RECEIVED = "received", _("Received: waiting to start")
    MODELS = "models", _("Models and scanning")
    DESIGN = "design", _("CAD design")
    DESIGN_CHECK = "design_check", _("Design check")
    MILLING = "milling", _("Milling")
    PRINTING = "printing", _("3D printing")
    METAL_PRINTING = "metal_printing", _("Metal printing (laser)")
    CASTING = "casting", _("Wax-up and casting")
    SINTERING = "sintering", _("Sintering / crystallization")
    CERAMIC = "ceramic", _("Ceramic build-up")
    STAIN_GLAZE = "stain_glaze", _("Stain and glaze")
    SETUP = "setup", _("Teeth set-up")
    PROCESSING = "processing", _("Processing (acrylic)")
    FINISHING = "finishing", _("Finishing and polishing")
    QC = "qc", _("Quality check")
    READY = "ready", _("Ready to deliver")
    DELIVERED = "delivered", _("Delivered to the clinic")
    TRY_IN = "try_in", _("At the clinic for a try-in")
    OUTSOURCED = "outsourced", _("At another lab")
    ON_HOLD = "on_hold", _("On hold: waiting for the doctor")
    CANCELLED = "cancelled", _("Cancelled")


# Steps where someone of the lab works on the case (they can be given to a person).
WORK_STEPS = (Step.MODELS, Step.DESIGN, Step.DESIGN_CHECK, Step.MILLING, Step.PRINTING, Step.METAL_PRINTING,
              Step.CASTING, Step.SINTERING, Step.CERAMIC, Step.STAIN_GLAZE, Step.SETUP, Step.PROCESSING,
              Step.FINISHING, Step.QC)
# Off the usual road: the case waits outside the lab's hands.
AWAY_STEPS = (Step.TRY_IN, Step.OUTSOURCED, Step.ON_HOLD)
CLOSED_STEPS = (Step.DELIVERED, Step.CANCELLED)
OPEN_STEPS = tuple(code for code in Step.values if code not in CLOSED_STEPS)

# The usual road of each kind of work (the case keeps its own copy, which the manager can change).
C = LabCategory
ROUTES = {
    C.ZIRCONIA: [Step.RECEIVED, Step.DESIGN, Step.MILLING, Step.SINTERING, Step.STAIN_GLAZE, Step.QC, Step.READY],
    C.EMAX: [Step.RECEIVED, Step.DESIGN, Step.MILLING, Step.SINTERING, Step.STAIN_GLAZE, Step.QC, Step.READY],
    C.PFM: [Step.RECEIVED, Step.DESIGN, Step.CASTING, Step.CERAMIC, Step.STAIN_GLAZE, Step.QC, Step.READY],
    C.RESIN_PRINT: [Step.RECEIVED, Step.DESIGN, Step.PRINTING, Step.FINISHING, Step.QC, Step.READY],
    C.PMMA: [Step.RECEIVED, Step.DESIGN, Step.MILLING, Step.FINISHING, Step.QC, Step.READY],
    C.METAL_PRINT: [Step.RECEIVED, Step.DESIGN, Step.METAL_PRINTING, Step.FINISHING, Step.QC, Step.READY],
    C.TI_MILL: [Step.RECEIVED, Step.DESIGN, Step.MILLING, Step.FINISHING, Step.QC, Step.READY],
    C.PRINT_MILL: [Step.RECEIVED, Step.DESIGN, Step.METAL_PRINTING, Step.MILLING, Step.FINISHING, Step.QC, Step.READY],
    C.REMOVABLE: [Step.RECEIVED, Step.MODELS, Step.SETUP, Step.PROCESSING, Step.FINISHING, Step.QC, Step.READY],
    C.SPLINT: [Step.RECEIVED, Step.DESIGN, Step.PRINTING, Step.FINISHING, Step.QC, Step.READY],
    C.OTHER: [Step.RECEIVED, Step.DESIGN, Step.FINISHING, Step.QC, Step.READY],
}

# The icon of each step on the board and the case page.
STEP_ICONS = {
    Step.INCOMING: "bi-truck", Step.RECEIVED: "bi-inbox", Step.MODELS: "bi-boxes", Step.DESIGN: "bi-vector-pen",
    Step.DESIGN_CHECK: "bi-eye", Step.MILLING: "bi-gear-wide-connected", Step.PRINTING: "bi-printer",
    Step.METAL_PRINTING: "bi-lightning-charge", Step.CASTING: "bi-fire", Step.SINTERING: "bi-thermometer-high",
    Step.CERAMIC: "bi-brush", Step.STAIN_GLAZE: "bi-palette", Step.SETUP: "bi-grid-3x2-gap",
    Step.PROCESSING: "bi-droplet", Step.FINISHING: "bi-stars", Step.QC: "bi-patch-check", Step.READY: "bi-bag-check",
    Step.DELIVERED: "bi-check2-all", Step.TRY_IN: "bi-arrow-left-right", Step.OUTSOURCED: "bi-building",
    Step.ON_HOLD: "bi-pause-circle", Step.CANCELLED: "bi-x-circle",
}


class LabPriceList(models.Model):
    """A price list of the lab, e.g. CIA's prices, El Khadem's prices, outside clinics."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("lab price list")
        verbose_name_plural = _("lab price lists")

    def __str__(self):
        return self.name


class LabPrice(models.Model):
    price_list = models.ForeignKey(LabPriceList, verbose_name=_("price list"), on_delete=models.CASCADE,
                                   related_name="prices")
    work_type = models.ForeignKey("clinical.LabWorkType", verbose_name=_("work"), on_delete=models.CASCADE,
                                  related_name="lab_prices")
    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = _("lab price")
        verbose_name_plural = _("lab prices")
        constraints = [models.UniqueConstraint(fields=["price_list", "work_type"], name="unique_lab_price")]

    def __str__(self):
        return f"{self.price_list} · {self.work_type}: {self.price}"


class LabClient(models.Model):
    """Who sends work to the lab: one of our places, or an outside clinic or doctor. Each has its price list."""

    class Kind(models.TextChoices):
        PLACE = "place", _("One of our places")
        CLINIC = "clinic", _("Outside clinic")
        DOCTOR = "doctor", _("Outside doctor")

    name = models.CharField(_("name"), max_length=150)
    kind = models.CharField(_("client"), max_length=10, choices=Kind.choices, default=Kind.CLINIC)
    branch = models.OneToOneField(Branch, verbose_name=_("our place"), null=True, blank=True,
                                  on_delete=models.PROTECT, related_name="lab_client")
    price_list = models.ForeignKey(LabPriceList, verbose_name=_("price list"), null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="clients")
    contact = models.CharField(_("doctor / contact person"), max_length=120, blank=True)
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    whatsapp = models.CharField(_("WhatsApp"), max_length=20, blank=True,
                                help_text=_("Empty = the mobile. The case's messages and answers go here."))
    address = models.CharField(_("address"), max_length=255, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = _("lab client")
        verbose_name_plural = _("lab clients")

    def __str__(self):
        if self.branch_id:
            return self.branch.name
        return self.name

    def get_absolute_url(self):
        return reverse("lab:client_detail", args=[self.pk])

    @property
    def whatsapp_phone(self):
        return self.whatsapp or self.phone or (self.branch.phone if self.branch_id else "")


class LabWorker(models.Model):
    """Someone who works on the cases: a designer (mostly CIA doctors, with their login), a technician (with or without
    a login), the head of the lab. The manager gives each step of a case to one of them."""

    name = models.CharField(_("name"), max_length=100)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name=_("login"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="lab_worker",
                                help_text=_("With a login they see their own work (My lab work) and are told when a "
                                            "case is given to them."))
    jobs = models.JSONField(_("works on"), default=list, blank=True)
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    fee_per_unit = models.DecimalField(
        _("paid per unit designed"), max_digits=8, decimal_places=2, null=True, blank=True,
        help_text=_("For designers paid by the unit (e.g. CIA doctors): the lab report adds up what they are owed."))
    is_active = models.BooleanField(_("active"), default=True)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = _("lab worker")
        verbose_name_plural = _("lab staff")

    def __str__(self):
        return self.name

    def job_labels(self):
        names = dict(Step.choices)
        return [names[code] for code in self.jobs or [] if code in names]

    def does(self, step):
        return step in (self.jobs or [])


class LabCase(TimeStampedModel):
    """One work received by the lab, from the moment it comes in until it is delivered back."""

    class Impression(models.TextChoices):
        DIGITAL = "digital", _("Digital (intraoral scan)")
        CONVENTIONAL = "conventional", _("Conventional impression")
        MODELS = "models", _("Models (poured)")

    class RemakeReason(models.TextChoices):
        FIT = "fit", _("Does not fit / open margin")
        CONTACTS = "contacts", _("Contacts (tight / open)")
        OCCLUSION = "occlusion", _("Occlusion (high / low)")
        SHADE = "shade", _("Shade")
        SHAPE = "shape", _("Shape / aesthetics")
        FRACTURE = "fracture", _("Fracture / chipping")
        DESIGN = "design", _("Design")
        IMPRESSION = "impression", _("Impression or scan problem")
        PATIENT = "patient", _("The patient's request")
        OTHER = "other", _("Other")

    class Fault(models.TextChoices):
        LAB = "lab", _("The lab")
        CLINIC = "clinic", _("The clinic / the doctor")
        PATIENT = "patient", _("The patient")
        UNKNOWN = "unknown", _("Not known yet")

    number = models.CharField(_("case number"), max_length=20, unique=True, blank=True, editable=False)
    client = models.ForeignKey(LabClient, verbose_name=_("client"), on_delete=models.PROTECT, related_name="cases")
    request = models.OneToOneField(LabRequest, verbose_name=_("lab request of our place"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="lab_case")
    remake_of = models.ForeignKey("self", verbose_name=_("remake of"), null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="remakes")
    remake_reason = models.CharField(_("why the remake"), max_length=12, choices=RemakeReason.choices, blank=True)
    remake_fault = models.CharField(_("whose fault"), max_length=8, choices=Fault.choices, blank=True)
    doctor = models.CharField(_("doctor"), max_length=120, blank=True)
    doctor_phone = models.CharField(_("doctor's mobile"), max_length=20, blank=True,
                                    help_text=_("The WhatsApp messages of this case go here (else to the client)."))
    patient_name = models.CharField(_("patient"), max_length=150, blank=True)
    impression = models.CharField(_("impression"), max_length=12, choices=Impression.choices,
                                  default=Impression.DIGITAL)
    enclosures = models.JSONField(_("came with the work"), default=list, blank=True)
    stage = models.CharField(_("send for"), max_length=12, choices=LabRequest.Stage.choices,
                             default=LabRequest.Stage.FINAL)
    shade = models.CharField(_("shade"), max_length=80, blank=True)
    instructions = models.TextField(_("instructions"), blank=True)
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("received by"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    due_date = models.DateField(_("promised for"), null=True, blank=True)
    urgent = models.BooleanField(_("urgent"), default=False)
    step = models.CharField(_("step"), max_length=15, choices=Step.choices, default=Step.RECEIVED, db_index=True)
    route = models.JSONField(_("steps of this case"), default=list, blank=True)
    step_since = models.DateTimeField(_("in this step since"), default=timezone.now)
    worker = models.ForeignKey(LabWorker, verbose_name=_("with"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="current_cases")
    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)
    delivered_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("delivered by"), null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    discount = models.DecimalField(_("discount"), max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(_("price of the case"), max_digits=12, decimal_places=2, default=0, editable=False)
    notes = models.TextField(_("notes of the lab"), blank=True)

    class Meta:
        ordering = ["-pk"]
        verbose_name = _("lab case")
        verbose_name_plural = _("lab cases")
        indexes = [models.Index(fields=["client", "delivered_at"]), models.Index(fields=["received_at"])]

    def __str__(self):
        return f"{self.number} · {self.patient_name or self.client}"

    def get_absolute_url(self):
        return reverse("lab:case_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                lab = Branch.objects.filter(kind=Branch.Kind.LAB).first()
                prefix = lab.badge if lab else "LAB"
                self.number = f"{prefix}-{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def is_open(self):
        return self.step not in CLOSED_STEPS

    @property
    def is_late(self):
        return self.is_open and self.due_date is not None and self.due_date < timezone.localdate()

    @property
    def is_remake(self):
        return self.remake_of_id is not None

    @property
    def units(self):
        return sum(item.units for item in self.items.all())

    @property
    def whatsapp_phone(self):
        return self.doctor_phone or self.client.whatsapp_phone

    @property
    def step_icon(self):
        return STEP_ICONS.get(self.step, "bi-circle")

    def work_summary(self):
        return " + ".join(f"{item.units} × {item.work_type}" for item in self.items.all())

    def recalc(self):
        """Add up the items (less the discount) and keep the total on the case, for quick lists and balances."""
        total = sum((item.amount for item in self.items.all()), Decimal("0")) - (self.discount or 0)
        self.total = max(total, Decimal("0"))
        type(self).objects.filter(pk=self.pk).update(total=self.total)
        return self.total


class LabCaseItem(models.Model):
    case = models.ForeignKey(LabCase, on_delete=models.CASCADE, related_name="items")
    work_type = models.ForeignKey("clinical.LabWorkType", verbose_name=_("work"), on_delete=models.PROTECT,
                                  related_name="lab_items")
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    units = models.PositiveSmallIntegerField(_("units"), default=1)
    material = models.CharField(_("material"), max_length=100, blank=True)
    unit_price = models.DecimalField(_("unit price"), max_digits=10, decimal_places=2, null=True, blank=True,
                                     help_text=_("Empty = the client's price list."))

    class Meta:
        ordering = ["pk"]
        verbose_name = _("work of a case")
        verbose_name_plural = _("work of a case")

    def __str__(self):
        return f"{self.units} × {self.work_type}"

    @property
    def amount(self):
        return (self.unit_price or Decimal("0")) * self.units


class LabCaseStep(models.Model):
    """One step of a case: when it came to this step, who worked on it, and when it left. The times between the steps
    make the lab's statistics."""

    case = models.ForeignKey(LabCase, on_delete=models.CASCADE, related_name="steps")
    step = models.CharField(_("step"), max_length=15, choices=Step.choices, db_index=True)
    worker = models.ForeignKey(LabWorker, verbose_name=_("done by"), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="steps")
    started_at = models.DateTimeField(_("from"), default=timezone.now)
    done_at = models.DateTimeField(_("to"), null=True, blank=True, db_index=True)
    completed = models.BooleanField(_("finished"), default=True,
                                    help_text=_("False when the case was put on hold before this step was finished."))
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("moved on by"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["started_at", "pk"]
        verbose_name = _("step of a case")
        verbose_name_plural = _("steps of the cases")

    def __str__(self):
        return f"{self.case} · {self.get_step_display()}"

    @property
    def hours(self):
        end = self.done_at or timezone.now()
        return (end - self.started_at).total_seconds() / 3600

    @property
    def icon(self):
        return STEP_ICONS.get(self.step, "bi-circle")


class LabOutsource(models.Model):
    """Work sent to another lab: what, when it went and came back, and what it cost."""

    case = models.ForeignKey(LabCase, on_delete=models.CASCADE, related_name="outsourced")
    lab = models.ForeignKey("clinical.Lab", verbose_name=_("sent to the lab"), on_delete=models.PROTECT,
                            related_name="outsourced_cases")
    work = models.CharField(_("what was sent"), max_length=150)
    sent_at = models.DateTimeField(_("sent at"), default=timezone.now)
    due_date = models.DateField(_("back by"), null=True, blank=True)
    back_at = models.DateTimeField(_("came back at"), null=True, blank=True)
    cost = models.DecimalField(_("cost"), max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("sent by"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = _("work sent to another lab")
        verbose_name_plural = _("work sent to other labs")

    def __str__(self):
        return f"{self.case.number} → {self.lab}"


class LabFile(models.Model):
    """A scan, a photo or a screenshot of the design, kept on the case."""

    class Kind(models.TextChoices):
        SCAN = "scan", _("Scan / STL")
        PHOTO = "photo", _("Photo")
        DESIGN = "design", _("Design (screenshot)")
        OTHER = "other", _("Other")

    case = models.ForeignKey(LabCase, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(_("kind"), max_length=8, choices=Kind.choices, default=Kind.PHOTO)
    file = models.FileField(_("file"), upload_to="lab/%Y/%m/")
    note = models.CharField(_("note"), max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    uploaded_at = models.DateTimeField(_("added at"), default=timezone.now)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = _("file of a case")
        verbose_name_plural = _("files of the cases")

    @property
    def is_image(self):
        return self.file.name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"))


class LabBlock(models.Model):
    """One block or disc opened for milling (zirconia, e.max, PMMA, wax, titanium): what was made from it."""

    class Status(models.TextChoices):
        IN_USE = "in_use", _("In use")
        FINISHED = "finished", _("Finished")
        BROKEN = "broken", _("Broken / thrown")

    item = models.ForeignKey("stock.StockItem", verbose_name=_("block / disc"), on_delete=models.PROTECT,
                             related_name="lab_blocks")
    code = models.CharField(_("block number"), max_length=30, blank=True,
                            help_text=_("Written on the block. Empty = given by itself (B-0001...)."))
    lot = models.CharField(_("lot"), max_length=60, blank=True)
    shade = models.CharField(_("shade"), max_length=20, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.IN_USE,
                              db_index=True)
    opened_at = models.DateTimeField(_("opened at"), default=timezone.now)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("opened by"), null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)
    unit_cost = models.DecimalField(_("cost of the block"), max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        verbose_name = _("block / disc")
        verbose_name_plural = _("blocks and discs")

    def __str__(self):
        return f"{self.code} · {self.item.name}"

    def get_absolute_url(self):
        return reverse("lab:block_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:
            self.code = f"B-{self.pk:04d}"
            type(self).objects.filter(pk=self.pk).update(code=self.code)


class LabBlockUse(models.Model):
    """Units of a case milled from a block."""

    block = models.ForeignKey(LabBlock, verbose_name=_("block"), on_delete=models.CASCADE, related_name="uses")
    case = models.ForeignKey(LabCase, verbose_name=_("case"), on_delete=models.CASCADE, related_name="block_uses")
    units = models.PositiveSmallIntegerField(_("units made"), default=1)
    used_at = models.DateTimeField(_("date"), default=timezone.now)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("by"), null=True, blank=True,
                           on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-used_at"]
        verbose_name = _("units made from a block")
        verbose_name_plural = _("units made from the blocks")


class LabPayment(models.Model):
    """A receipt of the lab: money received from a client. It is never deleted: a mistake is cancelled with a reason."""

    number = models.CharField(_("receipt number"), max_length=20, unique=True, blank=True, editable=False)
    client = models.ForeignKey(LabClient, verbose_name=_("client"), on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    method = models.CharField(_("paid by"), max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_on = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    reference = models.CharField(_("reference"), max_length=60, blank=True,
                                 help_text=_("Transfer or cheque number."))
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("received by"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(_("written at"), default=timezone.now)
    cancelled_at = models.DateTimeField(_("cancelled at"), null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("cancelled by"), null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    cancel_reason = models.CharField(_("why cancelled"), max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = _("lab receipt")
        verbose_name_plural = _("lab receipts")

    def __str__(self):
        return f"{self.number} · {self.client} · {self.amount}"

    def get_absolute_url(self):
        return reverse("lab:payment_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"LR{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None


class LabMessage(models.Model):
    """A WhatsApp message of the lab: opened by the secretary (one click) or answered by itself."""

    class Kind(models.TextChoices):
        RECEIVED = "received", _("Case received")
        READY = "ready", _("Case ready")
        DELIVERED = "delivered", _("Case sent back")
        STATUS = "status", _("Answer: where the case is")
        AUTO = "auto", _("Automatic answer")
        STATEMENT = "statement", _("Account statement")

    case = models.ForeignKey(LabCase, null=True, blank=True, on_delete=models.CASCADE, related_name="messages")
    client = models.ForeignKey(LabClient, null=True, blank=True, on_delete=models.CASCADE, related_name="messages")
    kind = models.CharField(_("message"), max_length=10, choices=Kind.choices)
    phone = models.CharField(_("to"), max_length=20, blank=True)
    text = models.TextField(_("text"), blank=True)
    sent_at = models.DateTimeField(_("sent at"), default=timezone.now)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("by"), null=True, blank=True,
                           on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = _("lab WhatsApp message")
        verbose_name_plural = _("lab WhatsApp messages")


class LabSettings(models.Model):
    """The lab's own options (one row): the texts of its messages and the automatic WhatsApp answer."""

    received_text = models.TextField(
        _("message when a case is received"), blank=True,
        default="أهلاً د. {doctor}، استلمنا شغل المريض {patient} ({work}) في {lab}.\n"
                "رقم الحالة: {number}. الميعاد المتوقع: {due}.\n"
                "للمتابعة ابعت رقم الحالة على الرقم ده في أي وقت.")
    ready_text = models.TextField(
        _("message when a case is ready"), blank=True,
        default="أهلاً د. {doctor}، شغل المريض {patient} ({work}) جاهز في {lab}. رقم الحالة: {number}.")
    delivered_text = models.TextField(
        _("message when a case is sent back"), blank=True,
        default="أهلاً د. {doctor}، شغل المريض {patient} ({work}) خرج من {lab} في الطريق إليك. رقم الحالة: {number}.")
    auto_reply = models.BooleanField(
        _("answer the follow-ups by itself"), default=False,
        help_text=_("Needs the WhatsApp Business platform of Meta and the server reachable from the internet. "
                    "A doctor who sends a case number gets its real status at once."))
    wa_phone_number_id = models.CharField(_("WhatsApp phone number ID"), max_length=40, blank=True)
    wa_token = models.CharField(_("WhatsApp access token"), max_length=400, blank=True)
    wa_verify_token = models.CharField(_("webhook verify token"), max_length=100, blank=True,
                                       help_text=_("Any word you choose, written the same in Meta's page."))
    wa_app_secret = models.CharField(_("app secret"), max_length=100, blank=True,
                                     help_text=_("Checks that each message really comes from WhatsApp."))

    class Meta:
        verbose_name = _("lab options")
        verbose_name_plural = _("lab options")

    def __str__(self):
        return str(_("Lab options"))

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


def lab_branch():
    """The place of the lab (for its look, its phone and its stock)."""
    return Branch.objects.filter(kind=Branch.Kind.LAB).order_by("pk").first()


def name_of(obj):
    """An English or an Arabic name, whichever fits the language of the page."""
    english = (get_language() or "").startswith("en")
    return (getattr(obj, "name_en", "") if english else "") or getattr(obj, "name_ar", "") or str(obj)
