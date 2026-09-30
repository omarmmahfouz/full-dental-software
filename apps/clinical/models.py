from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, LookupModel, TimeStampedModel


class ChartEffect(models.TextChoices):
    """What a procedure does to the teeth it is recorded on (updates the dental chart)."""

    NONE = "none", _("No change to the dental chart")
    CARIES = "caries", _("Caries found")
    FILLING = "filling", _("Filling / restoration")
    RCT = "rct", _("Root canal treatment")
    CROWN = "crown", _("Crown on natural tooth")
    EXTRACTION = "extraction", _("Extraction (tooth becomes missing)")
    IMPLANT = "implant", _("Implant placed")
    UNCOVER = "uncover", _("Implant uncovered (2nd stage / healing abutment)")
    IMPRESSION = "impression", _("Impression / digital scan (implant stage)")
    DELIVERY = "delivery", _("Final prosthesis delivered (implant loaded / tooth crowned)")
    IMPLANT_FAILED = "implant_failed", _("Implant failed / removed (becomes missing)")
    HOPELESS = "hopeless", _("Tooth hopeless")
    SOUND = "sound", _("Tooth sound (clear findings)")


class StepGroup(models.TextChoices):
    """The kinds of work a treatment step belongs to: the dentist taps the kind, then the step itself (e.g.
    Endodontics → access / access and cleaning / obturation / all in a single visit)."""

    RECORDS = "records", _("Diagnosis and records")
    SURGERY = "surgery", _("Surgery and implants")
    IMPLANT_TEETH = "implant_teeth", _("Teeth on implants")
    ENDO = "endo", _("Endodontics (root canal)")
    FILLINGS = "fillings", _("Fillings")
    FIXED = "fixed", _("Crowns and bridges")
    REMOVABLE = "removable", _("Dentures")
    GUMS = "gums", _("Gums and cleaning")
    ORTHO = "ortho", _("Orthodontics and TMJ")
    OTHER = "other", _("Other")


STEP_GROUP_ICONS = {
    "records": "bi-clipboard2-pulse", "surgery": "bi-implant", "implant_teeth": "bi-bricks", "endo": "bi-droplet-half",
    "fillings": "bi-circle-half", "fixed": "bi-gem", "removable": "bi-emoji-smile", "gums": "bi-stars",
    "ortho": "bi-arrows-collapse", "other": "bi-three-dots",
}

# The photos and periapical X-rays a step should have (TreatmentStepType.shots), kept on the step
# (ClinicalPhoto.treatment_step and .shot).
STEP_SHOTS = [
    ("pa_before", _("Periapical X-ray before")),
    ("pa_working", _("Periapical X-ray: working length")),
    ("pa_cone", _("Periapical X-ray: master cone")),
    ("pa_after", _("Periapical X-ray after")),
    ("photo_before", _("Photo before")),
    ("photo_after", _("Photo after")),
    ("photo_shade", _("Photo with the shade tab")),
]


class TreatmentStepType(LookupModel):
    class Category(models.TextChoices):
        IMPLANT = "implant", _("Implant and surgery")
        RESTORATIVE = "restorative", _("Restorative and other")

    class Journey(models.TextChoices):
        IMPRESSION = "impression", _("Primary impression / diagnostic scan")
        CBCT = "cbct", _("CBCT")

    IMPLANT_EFFECTS = ("implant", "uncover", "implant_failed")

    category = models.CharField(_("plan section"), max_length=20, choices=Category.choices,
                                default=Category.RESTORATIVE)
    group = models.CharField(_("kind of work"), max_length=20, choices=StepGroup.choices, default=StepGroup.OTHER,
                             help_text=_("The dentist taps the kind of work, then this step."))
    journey_step = models.CharField(
        _("counts as the file's step"), max_length=12, choices=Journey.choices, blank=True,
        help_text=_("Recording it ticks this step of the patient's file (e.g. a primary impression)."))
    shots = models.CharField(
        _("photos and X-rays to take"), max_length=120, blank=True,
        help_text=_("Comma separated: pa_before, pa_working, pa_cone, pa_after, photo_before, photo_after, "
                    "photo_shade."))
    description_ar = models.CharField(
        _("simple explanation (Arabic)"), max_length=255, blank=True,
        help_text=_("Plain words for the reception and the patient, e.g. حشو أبيض بلون السن لسد التسوس."),
    )
    chart_effect = models.CharField(
        _("effect on dental chart"), max_length=20, choices=ChartEffect.choices, default=ChartEffect.NONE,
        help_text=_("When this step is recorded on tooth numbers, the chart of those teeth is updated this way."),
    )
    default_material = models.CharField(_("default material"), max_length=60, blank=True)
    surgery_procedure = models.CharField(
        _("matching surgery-chart procedure"), max_length=20, blank=True,
        choices=[
            ("extraction", _("Extraction")), ("flap", _("Flap")), ("simple_implant", _("Simple implant")),
            ("immediate_implant", _("Immediate implant")), ("expansion", _("Expansion")),
            ("splitting", _("Splitting")), ("closed_sinus", _("Closed sinus")), ("open_sinus", _("Open sinus")),
            ("gbr", _("GBR")), ("guided", _("Guided implant")),
        ],
        help_text=_("Planned items of this type are ticked automatically when the surgery chart records it."),
    )

    class Meta(LookupModel.Meta):
        verbose_name = _("treatment step type")
        verbose_name_plural = _("treatment step types")

    def shot_list(self):
        """[(code, label)] of the photos and X-rays this step should have."""
        wanted = [code.strip() for code in self.shots.split(",") if code.strip()]
        labels = dict(STEP_SHOTS)
        return [(code, labels[code]) for code in wanted if code in labels]


class TreatmentStep(TimeStampedModel):
    """One line of the treatment log: what was done, on which teeth, by whom, under which supervisor."""

    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT, related_name="treatment_steps"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", verbose_name=_("visit"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="treatment_steps",
    )
    step_type = models.ForeignKey(TreatmentStepType, verbose_name=_("step"), on_delete=models.PROTECT)
    teeth = models.CharField(_("teeth (FDI numbers)"), max_length=100, blank=True, help_text=_("e.g. 36, 37 or 11-13"))
    performed_at = models.DateTimeField(_("done at"), default=timezone.now)
    operator = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("operator"), null=True, blank=True,
        on_delete=models.PROTECT, related_name="treatments_operated",
    )
    assistant = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("assistant"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="treatments_assisted",
    )
    supervisor = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("supervisor"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="treatments_supervised",
    )
    surfaces = models.CharField(_("surfaces"), max_length=10, blank=True, help_text=_("e.g. MO, DO, MOD"))
    material = models.CharField(_("material"), max_length=60, blank=True)
    next_visit = models.CharField(_("next visit"), max_length=255, blank=True)
    chart_updated = models.BooleanField(_("dental chart updated"), default=False, editable=False)
    implant_system = models.CharField(_("implant system / brand"), max_length=100, blank=True)
    implant_size = models.CharField(_("implant size (diameter x length)"), max_length=50, blank=True)
    notes = models.TextField(_("details"), blank=True)
    # Supervisor sign-off
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("checked by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    verified_at = models.DateTimeField(_("checked at"), null=True, blank=True)
    grade = models.PositiveSmallIntegerField(
        _("grade"), null=True, blank=True, choices=[(i, str(i)) for i in range(1, 6)],
        help_text=_("Supervisor evaluation from 1 (poor) to 5 (excellent)."),
    )
    supervisor_comment = models.TextField(_("supervisor comment"), blank=True)

    class Meta:
        ordering = ["-performed_at"]
        verbose_name = _("treatment step")
        verbose_name_plural = _("treatment steps")

    def __str__(self):
        return f"{self.step_type} - {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("clinical:step_detail", args=[self.pk])

    @property
    def is_verified(self):
        return self.verified_at is not None


class Lab(models.Model):
    name = models.CharField(_("name"), max_length=120, unique=True)
    name_en = models.CharField(_("name (English)"), max_length=120, blank=True)
    branch = models.ForeignKey(
        Branch, verbose_name=_("our branch"), null=True, blank=True, on_delete=models.SET_NULL,
        help_text=_("Set when the lab is our own lab."),
    )
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    contact_person = models.CharField(_("contact person"), max_length=100, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("lab")
        verbose_name_plural = _("labs")

    def __str__(self):
        if self.name_en and (get_language() or "").startswith("en"):
            return self.name_en
        return self.name


class LabCategory(models.TextChoices):
    """The kind of lab work: it gives a case at our lab its usual road (design, milling, sintering...)."""

    ZIRCONIA = "zirconia", _("Zirconia")
    EMAX = "emax", _("E.max (lithium disilicate)")
    PFM = "pfm", _("Cast metal and porcelain (PFM)")
    RESIN_PRINT = "resin_print", _("3D printing in resin (models, guides, temporaries)")
    PMMA = "pmma", _("Milled PMMA (temporaries)")
    METAL_PRINT = "metal_print", _("Metal printing (CoCr / titanium)")
    TI_MILL = "ti_mill", _("Titanium milling")
    PRINT_MILL = "print_mill", _("Metal printed, then finished by milling")
    REMOVABLE = "removable", _("Removable dentures")
    SPLINT = "splint", _("Splints, night guards and orthodontic appliances")
    OTHER = "other", _("Other")


class LabWorkType(LookupModel):
    class Unit(models.TextChoices):
        TOOTH = "tooth", _("per tooth / unit")
        ARCH = "arch", _("per arch")
        CASE = "case", _("per case")

    default_days = models.PositiveSmallIntegerField(
        _("usual days at the lab"), null=True, blank=True,
        help_text=_("When sent, the date the work is needed back is set this many days later."))
    category = models.CharField(_("kind of work"), max_length=15, choices=LabCategory.choices,
                                default=LabCategory.OTHER,
                                help_text=_("Gives the usual steps at our lab: e.g. zirconia is designed, milled, "
                                            "sintered, stained and glazed."))
    unit = models.CharField(_("priced"), max_length=6, choices=Unit.choices, default=Unit.TOOTH)

    class Meta(LookupModel.Meta):
        verbose_name = _("lab work type")
        verbose_name_plural = _("lab work types")


class LabRequest(TimeStampedModel):
    """A lab prescription and its journey: reviewed → sent → received → delivered."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_REVIEW = "pending_review", _("Waiting for supervisor review")
        APPROVED = "approved", _("Reviewed - ready to send")
        COLLECTED = "collected", _("Taken from the dentist - at the reception")
        SENT = "sent", _("At the lab")
        RECEIVED = "received", _("Received from lab")
        DELIVERED = "delivered", _("Delivered to patient")
        CANCELLED = "cancelled", _("Cancelled")

    OPEN_STATUSES = (Status.DRAFT, Status.PENDING_REVIEW, Status.APPROVED, Status.COLLECTED, Status.SENT,
                     Status.RECEIVED)

    class WorkForm(models.TextChoices):
        PHYSICAL = "physical", _("Physical (impression / model): the secretary takes it and sends it")
        DIGITAL = "digital", _("Digital scan: the file goes to the lab")

    class ShadeGuide(models.TextChoices):
        CLASSICAL = "classical", _("VITA classical")
        MASTER = "3d_master", _("VITA 3D-Master")

    CLASSICAL_SHADES = ["A1", "A2", "A3", "A3.5", "A4", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "D2", "D3",
                        "D4"]
    MASTER_SHADES = ["0M1", "0M2", "0M3", "1M1", "1M2", "2L1.5", "2L2.5", "2M1", "2M2", "2M3", "2R1.5", "2R2.5",
                     "3L1.5", "3L2.5", "3M1", "3M2", "3M3", "3R1.5", "3R2.5", "4L1.5", "4L2.5", "4M1", "4M2", "4M3",
                     "4R1.5", "4R2.5", "5M1", "5M2", "5M3"]

    class Stage(models.TextChoices):
        FINAL = "final", _("Final work")
        FRAMEWORK = "framework", _("Framework try-in")
        BISQUE = "bisque", _("Bisque try-in")
        WAX = "wax", _("Wax try-in / wax-up")
        TEMPORARY = "temporary", _("Temporary (PMMA)")
        REPAIR = "repair", _("Repair / remake")

    class Margin(models.TextChoices):
        CHAMFER = "chamfer", _("Chamfer")
        HEAVY_CHAMFER = "heavy_chamfer", _("Heavy chamfer")
        SHOULDER = "shoulder", _("Shoulder")
        FEATHER = "feather", _("Knife edge / feather")
        VERTICAL = "vertical", _("Vertical (BOPT)")

    class Pontic(models.TextChoices):
        OVATE = "ovate", _("Ovate")
        RIDGE_LAP = "ridge_lap", _("Modified ridge lap")
        SANITARY = "sanitary", _("Sanitary (hygienic)")
        CONICAL = "conical", _("Conical")

    class Occlusion(models.TextChoices):
        NORMAL = "normal", _("Normal contacts")
        LIGHT = "light", _("Light contacts")
        OUT = "out", _("Out of occlusion")

    class Retention(models.TextChoices):
        SCREW = "screw", _("Screw-retained")
        CEMENT = "cement", _("Cement-retained")

    ENCLOSURES = [("impression", _("Impression")), ("opposing", _("Opposing impression / model")),
                  ("bite", _("Bite registration")), ("models", _("Models")), ("scan", _("Digital scan files")),
                  ("photos", _("Photos")), ("shade_photo", _("Photo with the shade tab")), ("facebow", _("Face bow")),
                  ("scan_bodies", _("Scan bodies")), ("analogs", _("Implant analogues")),
                  ("abutments", _("Abutments / Ti-bases")), ("guide", _("Surgical guide")),
                  ("old", _("The old prosthesis"))]

    number = models.CharField(_("request number"), max_length=20, unique=True, blank=True, editable=False)
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="lab_requests")
    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT, related_name="lab_requests"
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment", verbose_name=_("visit"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lab_requests",
    )
    lab = models.ForeignKey(Lab, verbose_name=_("lab"), on_delete=models.PROTECT, related_name="requests")
    work_type = models.ForeignKey(LabWorkType, verbose_name=_("work type"), on_delete=models.PROTECT)
    teeth = models.CharField(_("teeth (FDI numbers)"), max_length=100)
    units = models.PositiveSmallIntegerField(_("number of units"), default=1)
    work_form = models.CharField(_("the work goes as"), max_length=10, choices=WorkForm.choices,
                                 default=WorkForm.PHYSICAL)
    shade_guide = models.CharField(_("shade guide"), max_length=10, choices=ShadeGuide.choices, blank=True)
    shade = models.CharField(_("shade"), max_length=30, blank=True)
    material = models.CharField(_("material"), max_length=100, blank=True)
    instructions = models.TextField(_("instructions to the lab"), blank=True)
    dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("dentist"), null=True, on_delete=models.PROTECT,
        related_name="lab_requests",
    )
    supervisor = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("reviewed by supervisor"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="lab_requests_reviewed",
        help_text=_("Supervisors do not log in: choose who checked the request and it goes straight to the secretary."),
    )
    due_date = models.DateField(_("needed back by"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("reviewed by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("taken from the dentist by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    collected_at = models.DateTimeField(_("taken from the dentist at"), null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("sent by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("received by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    delivered_at = models.DateTimeField(_("delivered to patient at"), null=True, blank=True)
    remake_count = models.PositiveSmallIntegerField(_("times returned to lab"), default=0)
    lab_cost = models.DecimalField(_("lab cost"), max_digits=10, decimal_places=2, null=True, blank=True)
    # The detailed prescription (the elite lab request of El Khadem, and every place)
    stage = models.CharField(_("send for"), max_length=12, choices=Stage.choices, default=Stage.FINAL)
    shade_cervical = models.CharField(_("cervical third"), max_length=10, blank=True)
    shade_incisal = models.CharField(_("incisal third"), max_length=10, blank=True)
    stump_shade = models.CharField(_("prepared tooth (stump) shade"), max_length=5, blank=True)
    margin = models.CharField(_("finish line"), max_length=15, choices=Margin.choices, blank=True)
    pontic = models.CharField(_("pontic design"), max_length=12, choices=Pontic.choices, blank=True)
    occlusion = models.CharField(_("occlusion"), max_length=10, choices=Occlusion.choices, blank=True)
    retention = models.CharField(_("on implants: retention"), max_length=10, choices=Retention.choices, blank=True)
    implant_details = models.CharField(
        _("on implants: system, platform and abutment"), max_length=150, blank=True,
        help_text=_("e.g. Neodent GM 4.3, Ti-base, multi-unit 17°"))
    enclosures = models.JSONField(_("sent with the work"), default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("lab request")
        verbose_name_plural = _("lab requests")

    def __str__(self):
        return f"{self.number} - {self.work_type} - {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("clinical:lab_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"LR-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    def enclosure_labels(self):
        names = dict(self.ENCLOSURES)
        return [names[code] for code in self.enclosures or [] if code in names]

    @property
    def is_overdue(self):
        return (
            self.status == self.Status.SENT and self.due_date is not None and self.due_date < timezone.localdate()
        )

    @property
    def turnaround_days(self):
        if self.sent_at and self.received_at:
            return (self.received_at - self.sent_at).days
        return None


class LabRequestEvent(models.Model):
    """History of every action on a lab request (who reviewed, sent, received...)."""

    class Action(models.TextChoices):
        CREATED = "created", _("Created")
        SUBMITTED = "submitted", _("Sent for review")
        COLLECTED = "collected", _("Taken from the dentist by the reception")
        APPROVED = "approved", _("Reviewed and approved")
        RETURNED = "returned", _("Returned to doctor for changes")
        SENT = "sent", _("Sent to lab")
        RECEIVED = "received", _("Received from lab")
        REMAKE = "remake", _("Returned to lab for remake")
        DELIVERED = "delivered", _("Delivered to patient")
        CANCELLED = "cancelled", _("Cancelled")

    request = models.ForeignKey(LabRequest, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(_("action"), max_length=20, choices=Action.choices)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("by"), null=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(_("time"), default=timezone.now)
    checked_against_request = models.BooleanField(_("work checked against the request"), default=False)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["at", "pk"]
        verbose_name = _("lab request history")
        verbose_name_plural = _("lab request history")


class OutsideRequest(TimeStampedModel):
    """A printed request the patient takes to a CBCT centre or a medical lab (blood tests)."""

    class Kind(models.TextChoices):
        CBCT = "cbct", _("CBCT request")
        MEDICAL_LAB = "medical_lab", _("Medical lab request")

    class Region(models.TextChoices):
        UPPER = "upper", _("Upper jaw")
        LOWER = "lower", _("Lower jaw")
        BOTH = "both", _("Both jaws")
        TEETH = "teeth", _("Only the teeth written below")

    class FieldOfView(models.TextChoices):
        SMALL = "small", _("Small (a few teeth)")
        MEDIUM = "medium", _("Medium (one jaw)")
        LARGE = "large", _("Large (both jaws, sinuses)")

    TESTS = [
        ("cbc", _("CBC (complete blood count)")),
        ("fbs", _("Fasting blood sugar")),
        ("rbs", _("Random blood sugar")),
        ("hba1c", _("HbA1c")),
        ("pt_inr", _("PT / INR")),
        ("ptt", _("PTT")),
        ("liver", _("Liver function (ALT, AST)")),
        ("kidney", _("Kidney function (creatinine, urea)")),
        ("hbsag", _("HBsAg (hepatitis B)")),
        ("hcv", _("HCV antibodies (hepatitis C)")),
        ("hiv", _("HIV antibodies")),
        ("vitamin_d", _("Vitamin D")),
        ("calcium", _("Serum calcium")),
    ]
    PURPOSES = [
        ("implant", _("Implant planning")),
        ("guided", _("Guided surgery (surgical guide)")),
        ("sinus", _("Sinus / bone evaluation")),
        ("follow_up", _("Follow-up after surgery")),
        ("other", _("Other")),
    ]

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="outside_requests")
    kind = models.CharField(_("request"), max_length=20, choices=Kind.choices)
    requested_on = models.DateField(_("date"), default=timezone.localdate)
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("requested by"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="outside_requests")
    region = models.CharField(_("area to scan"), max_length=10, choices=Region.choices, blank=True)
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    field_of_view = models.CharField(_("field of view"), max_length=10, choices=FieldOfView.choices, blank=True)
    purposes = models.JSONField(_("for"), default=list, blank=True)
    tests = models.JSONField(_("tests"), default=list, blank=True)
    other_tests = models.CharField(_("other tests"), max_length=255, blank=True)
    notes = models.TextField(_("notes for the centre"), blank=True)

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        DONE_HERE = "done_here", _("Done in our clinic")
        DONE_OUTSIDE = "done_outside", _("Done at the centre")
        CANCELLED = "cancelled", _("Cancelled")

    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.REQUESTED)
    done_on = models.DateField(_("done on"), null=True, blank=True)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name=_("marked done by"))
    result = models.ForeignKey("patients.PatientDocument", verbose_name=_("the scan"), null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+",
                               help_text=_("The X-ray / CBCT record with the folder or the link of the scan."))

    class Meta:
        ordering = ["-requested_on", "-pk"]
        verbose_name = _("CBCT / medical lab request")
        verbose_name_plural = _("CBCT / medical lab requests")

    def __str__(self):
        return f"{self.get_kind_display()} — {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("clinical:outside_print", args=[self.pk])

    def test_labels(self):
        labels = dict(self.TESTS)
        return [labels[code] for code in self.tests if code in labels]

    def purpose_labels(self):
        labels = dict(self.PURPOSES)
        return [labels[code] for code in self.purposes if code in labels]
