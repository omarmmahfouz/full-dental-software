"""The Paper Reader's records: the lists from the dental system, the scanned files, their pages, Claude's readings,
the values read and checked, and the packages sent back to the dental system."""

import os
import uuid
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# US dollars per million tokens: (input, output, cache read, cache write). A batch costs half. A model that is not
# listed (e.g. a fallback model) is counted at the dearest price.
PRICES = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10"), Decimal("0.20"), Decimal("2.50")),
    "claude-opus-5": (Decimal("5"), Decimal("25"), Decimal("0.50"), Decimal("6.25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25"), Decimal("0.50"), Decimal("6.25")),
}
DEAREST = max(PRICES.values())
PAGE_TOKENS_IN, PAGE_TOKENS_OUT = 5000, 2500  # what one reading of a page usually takes


def reading_estimate(model, batched):
    """About what one reading of one page costs, in US dollars."""
    prices = PRICES.get(model, DEAREST)
    price = (PAGE_TOKENS_IN * prices[0] + PAGE_TOKENS_OUT * prices[1]) / Decimal(1000000)
    return price / 2 if batched else price


def new_token():
    return uuid.uuid4().hex


def original_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10] or ".pdf"
    return f"files/{instance.token}/original{ext}"


def page_path(instance, filename):
    return f"files/{instance.file.token}/page-{instance.number:03d}-{uuid.uuid4().hex[:6]}.jpg"


class SystemLists(models.Model):
    """The lists file made by the dental system (Old paper files → Lists for the reader): the place, the values to
    read with their labels and choices, and the place's registered patients (to find whose file it is). One row."""

    data = models.JSONField(default=dict)
    place_code = models.CharField(_("place"), max_length=10, blank=True)
    imported_at = models.DateTimeField(_("brought in at"), null=True, blank=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        verbose_name = _("lists from the dental system")

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def ready(self):
        return bool(self.data.get("fields"))

    @property
    def place(self):
        return self.data.get("place", {})


class KnownPatient(models.Model):
    """A patient registered in the dental system (from the lists file): to know whose file a paper file is."""

    file_number = models.CharField(_("file number"), max_length=20, unique=True)
    full_name = models.CharField(_("name"), max_length=150)
    national_id = models.CharField(max_length=20, blank=True, db_index=True)
    phone_primary = models.CharField(max_length=20, blank=True, db_index=True)
    phone_secondary = models.CharField(max_length=20, blank=True, db_index=True)
    values = models.JSONField(default=dict, help_text="The patient's values in the dental system, as text.")

    class Meta:
        ordering = ["file_number"]
        verbose_name = _("registered patient")

    def __str__(self):
        return f"{self.file_number} — {self.full_name}"


class ReaderSettings(models.Model):
    """How the files are read (Settings, the person in charge). One row."""

    class Mode(models.TextChoices):
        NOW = "now", _("Now (full price, about a minute a file)")
        BATCH = "batch", _("In a batch (half price, back within a few hours)")

    MODELS = [
        ("claude-opus-5-5", _("Claude Opus 5.5 (the most accurate)")),
        ("claude-sonnet-5-5", _("Claude Sonnet 5.5 (half the price)")),
    ]
    EFFORTS = [
        ("low", _("Low (the cheapest)")),
        ("medium", _("Medium (usual)")),
        ("high", _("High (hard handwriting; costs more)")),
    ]

    enabled = models.BooleanField(
        _("send the scanned pages to Claude to read"), default=False,
        help_text=_("The pages leave this PC and go to Anthropic (the company that makes Claude) over the internet "
                    "to be read. Anthropic does not use them to train its models. Switch on only after the "
                    "patients' consent and your lawyer's advice."))
    model = models.CharField(_("model"), max_length=40, choices=MODELS, default="claude-opus-5-5")
    effort = models.CharField(_("how hard it thinks"), max_length=10, choices=EFFORTS, default="medium")
    two_readings = models.BooleanField(
        _("read each page twice and compare"), default=True,
        help_text=_("Where the two readings differ, the field is marked for checking. It catches more mistakes and "
                    "costs twice as much."))
    default_mode = models.CharField(_("usual way of sending"), max_length=10, choices=Mode.choices,
                                    default=Mode.BATCH)
    monthly_limit = models.DecimalField(
        _("monthly limit (US dollars)"), max_digits=8, decimal_places=2, default=Decimal("100"),
        help_text=_("Nothing more is sent this month when the month's cost reaches it. 0 = no limit."))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("settings")

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def key_is_set(self):
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


class PaperFile(models.Model):
    """One patient's scanned paper file, from upload to export. ``error`` keeps a short code (and a detail after
    ":"), shown in each person's own language by ``problem``."""

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting to be read")
        READING = "reading", _("Being read")
        REVIEW = "review", _("To check")
        APPROVED = "approved", _("Approved: ready to send to the system")
        EXPORTED = "exported", _("Sent to the system")
        SET_ASIDE = "set_aside", _("Set aside (typed by hand)")
        FAILED = "failed", _("Could not be read")

    OPEN = (Status.WAITING, Status.READING, Status.REVIEW, Status.FAILED)
    PROBLEMS = {
        "off": _("Reading is switched off (Settings)."),
        "no_key": _("The key to Claude is not set on this PC (ANTHROPIC_API_KEY in the .env file)."),
        "limit": _("This month's limit for reading is reached (Settings)."),
        "key_refused": _("The key to Claude was refused: check ANTHROPIC_API_KEY in the .env file."),
        "bad_pdf": _("This file cannot be opened as a PDF (%(error)s). Scan it again or save it again as a PDF."),
        "unread": _("Claude could not read this file. Check the scan, then press Read again, or type it by hand."),
    }

    token = models.CharField(max_length=32, default=new_token, unique=True, editable=False)
    upload = models.CharField(max_length=32, blank=True, db_index=True)
    place_code = models.CharField(_("place"), max_length=10, blank=True)
    original = models.FileField(_("the scan as it was uploaded"), upload_to=original_path)
    original_name = models.CharField(_("file name"), max_length=255)
    mode = models.CharField(_("sent"), max_length=10, choices=ReaderSettings.Mode.choices,
                            default=ReaderSettings.Mode.BATCH)
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.WAITING,
                              db_index=True)
    page_count = models.PositiveSmallIntegerField(_("pages"), default=0)
    cover_number = models.CharField(_("file number on the cover sheet"), max_length=30, blank=True)
    suggested = models.CharField(_("seems to be the file"), max_length=20, blank=True)
    suggested_reason = models.CharField(max_length=20, blank=True)
    error = models.CharField(_("problem"), max_length=500, blank=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True, editable=False)
    # What the person approved: {"target": "new" | "existing", "file_number", "patient": {...}, "history": {...},
    # "replace": [...]}; sent to the dental system in the package.
    approved = models.JSONField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    exported_in = models.ForeignKey("Export", null=True, blank=True, on_delete=models.SET_NULL, related_name="files")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("paper file")
        verbose_name_plural = _("paper files")

    def __str__(self):
        return self.original_name

    def get_absolute_url(self):
        return reverse("reading:review", args=[self.pk])

    @property
    def is_open(self):
        return self.status in self.OPEN

    @property
    def problem(self):
        code, _colon, detail = self.error.partition(":")
        message = self.PROBLEMS.get(code)
        if message is None:
            return self.error
        return str(message) % {"error": detail} if code == "bad_pdf" else str(message)

    def mark(self, status, error=""):
        self.status, self.error = status, error[:500]
        type(self).objects.filter(pk=self.pk).update(status=status, error=self.error)


class PaperPage(models.Model):
    """A page of a paper file, as an upright picture (the one Claude read)."""

    class Kind(models.TextChoices):
        COVER = "cover", _("Cover sheet (file number)")
        ID_FRONT = "id_front", _("ID card - front")
        ID_BACK = "id_back", _("ID card - back")
        REGISTRATION = "registration", _("Registration (patient's data)")
        HISTORY = "history", _("Medical and dental history")
        EXAMINATION = "examination", _("Examination")
        TOOTH_CHART = "tooth_chart", _("Dental chart (drawing of the teeth)")
        PLAN = "plan", _("Treatment plan")
        SURGERY = "surgery", _("Surgery chart")
        TREATMENT_LOG = "treatment_log", _("Treatment log (visits)")
        PRESCRIPTION = "prescription", _("Prescription")
        LAB = "lab", _("Lab paper")
        CONSENT = "consent", _("Signed consent")
        RECEIPT = "receipt", _("Receipt or payments")
        XRAY = "xray", _("X-ray, CBCT or photo")
        OTHER = "other", _("Other")
        BLANK = "blank", _("Blank page")

    # The order of the pages in the clean file kept in the patient's documents; cover sheets and blank pages are left out.
    ORDER = [Kind.ID_FRONT, Kind.ID_BACK, Kind.REGISTRATION, Kind.HISTORY, Kind.EXAMINATION, Kind.TOOTH_CHART,
             Kind.PLAN, Kind.SURGERY, Kind.TREATMENT_LOG, Kind.PRESCRIPTION, Kind.LAB, Kind.CONSENT, Kind.RECEIPT,
             Kind.XRAY, Kind.OTHER]
    LEFT_OUT = (Kind.COVER, Kind.BLANK)

    file = models.ForeignKey(PaperFile, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveSmallIntegerField(_("page"))
    image = models.FileField(_("picture"), upload_to=page_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    kind = models.CharField(_("what the page is"), max_length=20, choices=Kind.choices, blank=True)
    turned = models.PositiveSmallIntegerField(_("turned (degrees, clockwise)"), default=0)
    notes = models.CharField(_("notes"), max_length=300, blank=True)

    class Meta:
        ordering = ["file", "number"]
        constraints = [models.UniqueConstraint(fields=["file", "number"], name="reader_page_once")]

    def __str__(self):
        return f"{self.file} p{self.number}"

    @property
    def place_in_file(self):
        kinds = [str(kind) for kind in self.ORDER]
        return (kinds.index(self.kind) if self.kind in kinds else len(kinds), self.number)


class PaperReading(models.Model):
    """One reading of one page by Claude (twice when the settings say so)."""

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting")
        SENDING = "sending", _("Being sent")
        SENT = "sent", _("Sent")
        DONE = "done", _("Read")
        FAILED = "failed", _("Not read")

    page = models.ForeignKey(PaperPage, on_delete=models.CASCADE, related_name="readings")
    number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING, db_index=True)
    batch_id = models.CharField(max_length=100, blank=True, db_index=True)
    batched = models.BooleanField(default=False)
    model = models.CharField(max_length=60, blank=True)
    result = models.JSONField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    tries = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["page", "number"]
        constraints = [models.UniqueConstraint(fields=["page", "number"], name="reader_reading_once")]

    def __str__(self):
        return f"{self.page} #{self.number}"

    @property
    def cost(self):
        prices = PRICES.get(self.model, DEAREST)
        total = (self.input_tokens * prices[0] + self.output_tokens * prices[1] + self.cache_read_tokens * prices[2]
                 + self.cache_write_tokens * prices[3]) / Decimal(1000000)
        return total / 2 if self.batched else total


class PaperField(models.Model):
    """One value read from a paper file, checked, and proposed to the person."""

    class Certainty(models.TextChoices):
        SURE = "sure", _("Sure")
        CHECK = "check", _("Please check")
        UNCLEAR = "unclear", _("Cannot be read")

    file = models.ForeignKey(PaperFile, on_delete=models.CASCADE, related_name="fields")
    page = models.ForeignKey(PaperPage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    name = models.CharField(max_length=60)
    value = models.TextField(blank=True)
    written = models.TextField(blank=True)
    other = models.TextField(blank=True)
    certainty = models.CharField(max_length=10, choices=Certainty.choices, default=Certainty.SURE)
    problems = models.JSONField(default=list, blank=True)
    note = models.CharField(max_length=300, blank=True)
    box = models.JSONField(null=True, blank=True, help_text="[left, top, right, bottom] on the upright page picture.")
    checked = models.BooleanField(default=False)

    class Meta:
        ordering = ["file", "pk"]
        constraints = [models.UniqueConstraint(fields=["file", "name"], name="reader_field_once")]

    def __str__(self):
        return f"{self.name}: {self.value}"

    @property
    def needs_look(self):
        return self.certainty != self.Certainty.SURE and not self.checked

    def reasons(self):
        from .checks import explain

        return [explain(code, params) for code, params in self.problems]


class Export(models.Model):
    """A package of approved files made for the dental system (its Old paper files → Import)."""

    made_at = models.DateTimeField(_("made at"), auto_now_add=True)
    made_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    place_code = models.CharField(_("place"), max_length=10)
    name = models.CharField(_("file name"), max_length=120)
    package = models.FileField(upload_to="exports/")
    count = models.PositiveIntegerField(_("files"), default=0)

    class Meta:
        ordering = ["-made_at", "-pk"]
        verbose_name = _("package for the system")

    def __str__(self):
        return self.name


def month_cost(today=None):
    """What the readings of this month cost, in US dollars."""
    today = today or timezone.localdate()
    start = timezone.make_aware(datetime(today.year, today.month, 1))
    readings = PaperReading.objects.filter(done_at__gte=start).only(
        "model", "batched", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    return sum((reading.cost for reading in readings), Decimal("0"))
