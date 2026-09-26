import os
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.charting.teeth import TOOTH_CHOICES
from apps.core.models import Branch, TimeStampedModel


class ImplantSystem(models.Model):
    """Implant company and line, e.g. Osstem - TS III."""

    company = models.CharField(_("company"), max_length=80)
    line = models.CharField(_("implant type / line"), max_length=80, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["company", "line"]
        verbose_name = _("implant system")
        verbose_name_plural = _("implant systems")
        constraints = [models.UniqueConstraint(fields=["company", "line"], name="unique_implant_system")]

    def __str__(self):
        return f"{self.company} {self.line}".strip()


class Surgery(TimeStampedModel):
    """One surgery (the CIA surgery chart)."""

    class Difficulty(models.TextChoices):
        SIMPLE = "simple", _("Simple")
        MODERATE = "moderate", _("Moderate")
        ADVANCED = "advanced", _("Advanced (sinus / GBR / block)")

    class BlockDonor(models.TextChoices):
        CHIN = "chin", _("Chin")
        RAMUS = "ramus", _("Ramus")
        TUBEROSITY = "tuberosity", _("Tuberosity")
        OTHER = "other", _("Other")

    class CutBy(models.TextChoices):
        DISC = "disc", _("Disc")
        PIEZO = "piezo", _("Piezo")

    class Particle(models.TextChoices):
        AUTOGENOUS = "autogenous", _("Autogenous only (100%)")
        XENOGRAFT = "xenograft", _("Xenograft only (100%)")
        MIX = "mix", _("Mix autogenous : xenograft")

    class SoftTissueGraft(models.TextChoices):
        FGG = "fgg", _("Free gingival graft")
        CTG = "ctg", _("Connective tissue graft")
        OTHER = "other", _("Other soft tissue graft")

    class SutureSize(models.TextChoices):
        S3 = "3-0", "3-0"
        S4 = "4-0", "4-0"
        S5 = "5-0", "5-0"
        S6 = "6-0", "6-0"
        S7 = "7-0", "7-0"

    class SutureMaterial(models.TextChoices):
        VICRYL = "vicryl", _("Vicryl")
        PROLENE = "prolene", _("Prolene")
        SILK = "silk", _("Silk")
        OTHER = "other", _("Other")

    class Temporary(models.TextChoices):
        NONE = "none", _("None")
        HEALING_COLLAR = "healing_collar", _("Healing collar")
        CUSTOM_HEALING = "custom_healing", _("Customized healing collar")
        CROWN = "crown", _("Crown")
        MARYLAND = "maryland", _("Maryland bridge")
        BRIDGE_ON_TEETH = "bridge_on_teeth", _("Bridge on teeth")
        DENTURE_FIBER = "denture_fiber", _("Denture with glass fiber")

    number = models.CharField(_("surgery number"), max_length=20, unique=True, blank=True, editable=False)
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="surgeries")
    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT, related_name="surgeries"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", verbose_name=_("visit"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgeries",
    )
    date = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    instructor = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("instructor"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgeries_instructed",
    )
    operator_1 = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("operator 1"), on_delete=models.PROTECT, related_name="surgeries_as_op1"
    )
    operator_2 = models.ForeignKey(  # works on other teeth (the operator of each tooth is on the site)
        "dentists.Dentist", verbose_name=_("operator 2 (other teeth)"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgeries_as_op2",
    )
    assistant = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("assistant"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgeries_assisted",
    )
    difficulty = models.CharField(_("case difficulty"), max_length=20, choices=Difficulty.choices, default=Difficulty.SIMPLE)

    # Guided bone regeneration
    block_graft = models.BooleanField(_("block graft"), default=False)
    block_donor = models.CharField(_("block donor site"), max_length=20, choices=BlockDonor.choices, blank=True)
    block_donor_other = models.CharField(_("other donor site"), max_length=100, blank=True)
    cut_by = models.CharField(_("cut by"), max_length=10, choices=CutBy.choices, blank=True)
    screws_count = models.PositiveSmallIntegerField(_("number of screws"), null=True, blank=True)
    bone_particle = models.CharField(_("bone particle"), max_length=20, choices=Particle.choices, blank=True)
    autogenous_percent = models.PositiveSmallIntegerField(
        _("autogenous %"), null=True, blank=True, validators=[MaxValueValidator(100)],
        help_text=_("For a mix: the rest is xenograft."),
    )
    bone_material = models.CharField(_("bone graft material / brand"), max_length=120, blank=True)
    acm_bur_area = models.CharField(_("ACM bur - area"), max_length=120, blank=True)
    gbr_notes = models.TextField(_("GBR notes"), blank=True)

    # Open sinus lift
    sinus_approach = models.CharField(_("sinus approach"), max_length=120, blank=True)
    sinus_fill_material = models.CharField(_("sinus fill material"), max_length=120, blank=True)
    sinus_notes = models.TextField(_("sinus notes"), blank=True)

    # Membrane and tacks (GBR / sinus)
    membrane_used = models.BooleanField(_("membrane used"), default=False)
    membrane_size = models.CharField(_("membrane size (mm x mm)"), max_length=30, blank=True)
    membrane_material = models.CharField(_("membrane material"), max_length=100, blank=True)
    membrane_company = models.CharField(_("membrane company"), max_length=100, blank=True)
    tacks_count = models.PositiveSmallIntegerField(_("number of tacks"), null=True, blank=True)
    tacks_company = models.CharField(_("tacks company"), max_length=100, blank=True)

    # Soft tissue
    soft_tissue_graft = models.CharField(_("soft tissue graft"), max_length=10, choices=SoftTissueGraft.choices, blank=True)
    soft_tissue_technique = models.CharField(_("surgery technique"), max_length=150, blank=True)
    exposure = models.BooleanField(_("exposure"), null=True, blank=True)
    custom_healing_teeth = models.CharField(_("customized healing collar - teeth"), max_length=100, blank=True)
    donor_site = models.CharField(_("donor site"), max_length=150, blank=True)
    soft_tissue_suture_material = models.CharField(_("soft tissue suture material"), max_length=100, blank=True)
    soft_tissue_suture_technique = models.CharField(_("soft tissue suture technique"), max_length=100, blank=True)
    pack_type = models.CharField(_("pack type"), max_length=100, blank=True)
    recipient_area = models.CharField(_("recipient site - area"), max_length=150, blank=True)
    augmentation_sites = models.CharField(
        _("augmentation site"), max_length=30, blank=True, help_text=_("Buccal, crestal, lingual, mesial, distal.")
    )
    frenectomy = models.CharField(_("frenectomy"), max_length=150, blank=True)
    soft_tissue_bone_graft = models.CharField(_("bone graft with soft tissue surgery (type & site)"), max_length=150, blank=True)
    soft_tissue_notes = models.TextField(_("soft tissue notes"), blank=True)

    # Suture, temporization, X-ray
    suture_size = models.CharField(_("suture size"), max_length=5, choices=SutureSize.choices, blank=True)
    suture_material = models.CharField(_("suture material"), max_length=10, choices=SutureMaterial.choices, blank=True)
    suture_technique = models.CharField(_("suture technique"), max_length=100, blank=True)
    xray_taken = models.BooleanField(_("X-ray taken"), default=False)
    xray_notes = models.CharField(_("X-ray notes"), max_length=200, blank=True)
    temporary = models.CharField(_("temporary"), max_length=20, choices=Temporary.choices, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    complications = models.TextField(_("complications / post-operative notes"), blank=True)
    chart_updated = models.BooleanField(_("dental chart updated"), default=False, editable=False)

    AUGMENTATION_CHOICES = [
        ("B", _("Buccal")), ("C", _("Crestal")), ("L", _("Lingual")), ("M", _("Mesial")), ("D", _("Distal")),
    ]

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = _("surgery")
        verbose_name_plural = _("surgeries")

    def __str__(self):
        return f"{self.number} - {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("surgery:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"SUR-{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def xenograft_percent(self):
        if self.bone_particle == self.Particle.MIX and self.autogenous_percent is not None:
            return 100 - self.autogenous_percent
        return None

    def augmentation_labels(self):
        chosen = set(self.augmentation_sites.split(",")) if self.augmentation_sites else set()
        return [str(label) for code, label in self.AUGMENTATION_CHOICES if code in chosen]

    def team(self):
        return [d for d in (self.operator_1, self.operator_2, self.assistant) if d]


def mm(value):
    """4.50 -> "4.5", 10.0 -> "10" (implant sizes as dentists write them)."""
    return "" if value is None else format(value.normalize(), "f")


def sticker_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"patients/{instance.surgery.patient_id}/stickers/{uuid.uuid4().hex}{ext}"


class SiteQuerySet(models.QuerySet):
    def done_by(self, dentist):
        """The teeth this dentist operated: his own teeth, or those of his surgeries with no other operator."""
        return self.filter(models.Q(operator=dentist) | models.Q(operator__isnull=True, surgery__operator_1=dentist))


class SurgerySite(models.Model):
    """One tooth position in a surgery (one column of the paper chart), with the
    implant placed there and its life afterwards (uncovered → loaded / failed)."""

    objects = SiteQuerySet.as_manager()

    class ImplantStatus(models.TextChoices):
        PLACED = "placed", _("Placed - healing")
        UNCOVERED = "uncovered", _("Uncovered (2nd stage)")
        IMPRESSION = "impression", _("Impression / scan taken")
        LOADED = "loaded", _("Loaded (final prosthesis)")
        FAILED = "failed", _("Failed / removed")

    STAGE_ORDER = [ImplantStatus.PLACED, ImplantStatus.UNCOVERED, ImplantStatus.IMPRESSION, ImplantStatus.LOADED]
    PROCEDURES = [
        ("extraction", _("Extraction")),
        ("flap", _("Flap")),
        ("simple_implant", _("Simple implant")),
        ("immediate_implant", _("Immediate implant")),
        ("expansion", _("Expansion")),
        ("splitting", _("Splitting")),
        ("closed_sinus", _("Closed sinus")),
        ("open_sinus", _("Open sinus")),
        ("gbr", _("GBR")),
        ("guided", _("Guided implant")),
    ]
    IMPLANT_PROCEDURES = ("simple_implant", "immediate_implant", "guided")

    surgery = models.ForeignKey(Surgery, on_delete=models.CASCADE, related_name="sites")
    tooth = models.PositiveSmallIntegerField(_("tooth"), choices=TOOTH_CHOICES)
    operator = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("operator of this tooth"), null=True, blank=True, on_delete=models.PROTECT,
        related_name="operated_sites",
        help_text=_("Operator 2 works on other teeth than operator 1. Empty: operator 1."))
    extraction = models.BooleanField(_("extraction"), default=False)
    flap = models.BooleanField(_("flap"), default=False)
    simple_implant = models.BooleanField(_("simple implant"), default=False)
    immediate_implant = models.BooleanField(_("immediate implant"), default=False)
    expansion = models.BooleanField(_("expansion"), default=False)
    splitting = models.BooleanField(_("splitting"), default=False)
    closed_sinus = models.BooleanField(_("closed sinus"), default=False)
    open_sinus = models.BooleanField(_("open sinus"), default=False)
    gbr = models.BooleanField(_("GBR"), default=False)
    guided = models.BooleanField(_("guided implant"), default=False)
    implant_system = models.ForeignKey(
        ImplantSystem, verbose_name=_("implant type"), null=True, blank=True, on_delete=models.PROTECT,
        related_name="sites",
    )
    implant_diameter = models.DecimalField(_("implant diameter (mm)"), max_digits=3, decimal_places=1, null=True, blank=True)
    implant_length = models.DecimalField(_("implant length (mm)"), max_digits=3, decimal_places=1, null=True, blank=True)
    lot_number = models.CharField(_("lot / ref number"), max_length=60, blank=True)
    implant_stock_item = models.ForeignKey(
        "stock.StockItem", verbose_name=_("implant from stock"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", editable=False)
    stock_movement = models.OneToOneField(
        "stock.StockMovement", null=True, blank=True, on_delete=models.SET_NULL, related_name="surgery_site",
        editable=False, help_text=_("The implant taken out of stock for this tooth."))
    sticker = models.FileField(_("implant sticker (photo)"), upload_to=sticker_path, blank=True)
    insertion_torque = models.PositiveSmallIntegerField(_("insertion torque (Ncm)"), null=True, blank=True)
    isq = models.PositiveSmallIntegerField(_("ISQ"), null=True, blank=True, validators=[MaxValueValidator(100)])
    subcrestal = models.BooleanField(_("implant subcrestal"), default=False)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    implant_status = models.CharField(_("implant status"), max_length=20, choices=ImplantStatus.choices, blank=True, db_index=True)
    uncovered_on = models.DateField(_("uncovered on"), null=True, blank=True)
    impression_on = models.DateField(_("impression / scan on"), null=True, blank=True)
    loaded_on = models.DateField(_("loaded on"), null=True, blank=True)
    failed_on = models.DateField(_("failed on"), null=True, blank=True)
    failure_reason = models.CharField(_("failure reason"), max_length=255, blank=True)

    class Meta:
        ordering = ["surgery", "tooth"]
        verbose_name = _("surgical site / implant")
        verbose_name_plural = _("surgical sites / implants")
        constraints = [models.UniqueConstraint(fields=["surgery", "tooth"], name="unique_tooth_per_surgery")]

    def __str__(self):
        if self.has_implant:
            return f"{self.tooth} - {self.implant_label}"
        return str(self.tooth)

    @property
    def done_by(self):
        return self.operator if self.operator_id else self.surgery.operator_1

    @property
    def has_implant(self):
        return any(getattr(self, name) for name in self.IMPLANT_PROCEDURES) or bool(
            self.implant_system_id or self.implant_diameter or self.implant_length
        )

    @property
    def implant_label(self):
        size = ""
        if self.implant_diameter and self.implant_length:
            size = f"{mm(self.implant_diameter)} x {mm(self.implant_length)}"
        return " ".join(part for part in (str(self.implant_system or ""), size) if part) or str(_("Implant"))

    @property
    def diameter_mm(self):
        return mm(self.implant_diameter)

    @property
    def length_mm(self):
        return mm(self.implant_length)

    def procedure_labels(self):
        return [str(label) for name, label in self.PROCEDURES if getattr(self, name)]

    def save(self, *args, **kwargs):
        if self.has_implant and not self.implant_status:
            self.implant_status = self.ImplantStatus.PLACED
        elif not self.has_implant:
            self.implant_status = ""
        super().save(*args, **kwargs)

    def advance(self, status, on=None):
        """Move the implant forward (never backwards) and stamp the date."""
        on = on or timezone.localdate()
        if status == self.ImplantStatus.FAILED:
            self.implant_status, self.failed_on = status, on
            return True
        if self.implant_status in ("", self.ImplantStatus.FAILED):
            return False
        if self.STAGE_ORDER.index(status) <= self.STAGE_ORDER.index(self.implant_status):
            return False
        self.implant_status = status
        field = {"uncovered": "uncovered_on", "impression": "impression_on", "loaded": "loaded_on"}[status]
        setattr(self, field, on)
        return True

    @property
    def days_to_loading(self):
        if self.loaded_on:
            return (self.loaded_on - self.surgery.date).days
        return None


class SavedSearch(models.Model):
    """A named set of case-finder filters (for repeated statistics / publications)."""

    name = models.CharField(_("name"), max_length=120)
    query = models.TextField(_("filters"))
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    shared = models.BooleanField(_("visible to all managers"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("saved search")
        verbose_name_plural = _("saved searches")

    def __str__(self):
        return self.name


class Prosthesis(TimeStampedModel):
    """What sits on the implants: a single crown, a bridge (how many units, on which implants,
    which teeth are pontics), or a full arch (fixed or overdenture)."""

    class Kind(models.TextChoices):
        SINGLE = "single", _("Single crown on implant")
        BRIDGE = "bridge", _("Bridge on implants")
        FULL_FIXED = "full_fixed", _("Full arch - fixed (All-on-X / hybrid)")
        OVERDENTURE = "overdenture", _("Full arch - overdenture (removable)")

    class Retention(models.TextChoices):
        SCREW = "screw", _("Screw-retained")
        CEMENT = "cement", _("Cement-retained")
        LOCATOR = "locator", _("Locators / attachments")
        BAR = "bar", _("Bar")
        BALL = "ball", _("Ball attachments")

    class Material(models.TextChoices):
        ZIRCONIA = "zirconia", _("Zirconia")
        PFM = "pfm", _("Porcelain fused to metal")
        EMAX = "emax", _("Lithium disilicate (e.max)")
        PMMA = "pmma", _("PMMA")
        ACRYLIC_BAR = "acrylic_bar", _("Acrylic teeth on a titanium bar")
        ACRYLIC = "acrylic", _("Acrylic denture")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IMPRESSION = "impression", _("Impression / scan taken")
        TRY_IN = "try_in", _("Try-in")
        DELIVERED = "delivered", _("Delivered")

    class Jaw(models.TextChoices):
        UPPER = "upper", _("Upper")
        LOWER = "lower", _("Lower")

    FULL_ARCH = (Kind.FULL_FIXED, Kind.OVERDENTURE)

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.CASCADE,
                                related_name="prostheses")
    kind = models.CharField(_("prosthesis"), max_length=20, choices=Kind.choices, default=Kind.SINGLE)
    jaw = models.CharField(_("jaw"), max_length=10, choices=Jaw.choices, blank=True)
    teeth = models.CharField(_("teeth it replaces (units)"), max_length=120, blank=True,
                             help_text=_("Every tooth of the bridge, e.g. 34-37. Teeth without an implant are pontics."))
    implants = models.ManyToManyField(SurgerySite, verbose_name=_("on the implants"), related_name="prostheses")
    retention = models.CharField(_("retention"), max_length=20, choices=Retention.choices, blank=True)
    material = models.CharField(_("material"), max_length=20, choices=Material.choices, blank=True)
    is_temporary = models.BooleanField(_("temporary"), default=False,
                                       help_text=_("A temporary does not mark the implants as loaded."))
    status = models.CharField(_("stage"), max_length=20, choices=Status.choices, default=Status.PLANNED)
    delivered_on = models.DateField(_("delivered on"), null=True, blank=True)
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("dentist"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="prostheses")
    lab_request = models.ForeignKey("clinical.LabRequest", verbose_name=_("lab request"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="prostheses")
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("implant prosthesis")
        verbose_name_plural = _("implant prostheses")

    def __str__(self):
        return self.label

    def get_absolute_url(self):
        return reverse("surgery:prosthesis_update", args=[self.pk])

    @property
    def unit_teeth(self):
        from apps.charting.teeth import parse_teeth

        try:
            return parse_teeth(self.teeth)
        except Exception:  # noqa: BLE001 - an old value that no longer reads is shown as it is
            return []

    @property
    def implant_teeth(self):
        return sorted(site.tooth for site in self.implants.all())

    @property
    def pontics(self):
        on_implants = set(self.implant_teeth)
        return [tooth for tooth in self.unit_teeth if tooth not in on_implants]

    @property
    def units(self):
        return len(self.unit_teeth)

    @property
    def label(self):
        from apps.charting.teeth import format_teeth

        where = self.get_jaw_display() if self.kind in self.FULL_ARCH and self.jaw else format_teeth(self.unit_teeth)
        text = f"{self.get_kind_display()} {where}".strip()
        count = len(self.implant_teeth)
        details = [ngettext("%(n)s implant", "%(n)s implants", count) % {"n": count}] if self.kind != self.Kind.SINGLE else []
        if self.units > 1:
            details.append(ngettext("%(n)s unit", "%(n)s units", self.units) % {"n": self.units})
        if self.pontics:
            details.append(ngettext("%(n)s pontic", "%(n)s pontics", len(self.pontics)) % {"n": len(self.pontics)})
        details = [d for d in details if d]
        return f"{text} ({', '.join(details)})" if details else text
