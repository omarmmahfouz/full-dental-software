import os
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import LookupModel, TimeStampedModel

from .teeth import TOOTH_CHOICES


class YesNo(models.TextChoices):
    YES = "yes", _("Yes")
    NO = "no", _("No")


class Examination(TimeStampedModel):
    """The diagnostic chart (pages 1-2 of the CIA paper chart): examination,
    medical history and dental history, filled by the dentist."""

    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.CASCADE, related_name="examinations"
    )
    exam_date = models.DateField(_("date of examination"), default=timezone.localdate)
    examined_by = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("examined by"), null=True, on_delete=models.SET_NULL, related_name="+"
    )
    supervisor = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("supervisor"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    referral = models.CharField(_("referral"), max_length=200, blank=True)
    chief_complaint = models.TextField(_("chief complaint"), blank=True)

    # Tooth findings at examination (also written onto the dental chart).
    teeth_carious = models.CharField(_("carious"), max_length=120, blank=True)
    teeth_filled = models.CharField(_("filled"), max_length=120, blank=True)
    teeth_missing = models.CharField(_("missed"), max_length=120, blank=True)
    teeth_not_sure = models.CharField(_("not sure"), max_length=120, blank=True)
    teeth_mobility = models.CharField(_("mobility"), max_length=120, blank=True)
    teeth_hopeless = models.CharField(_("hopeless teeth"), max_length=120, blank=True)
    teeth_implant_placed = models.CharField(_("implant placed (before coming to us)"), max_length=120, blank=True)
    teeth_implant_failed = models.CharField(_("implant failed (before coming to us)"), max_length=120, blank=True)
    inter_arch_space_right = models.CharField(_("inter-arch space - right"), max_length=100, blank=True)
    inter_arch_space_left = models.CharField(_("inter-arch space - left"), max_length=100, blank=True)
    operator_notices = models.TextField(_("operator important notices"), blank=True)
    cbct_requested = models.BooleanField(_("CBCT requested"), default=False)
    cbct_done = models.BooleanField(_("CBCT done"), default=False)
    new_cbct_requested = models.BooleanField(_("new CBCT requested"), default=False)

    # Medical health
    general_health = models.CharField(_("general health"), max_length=255, blank=True)
    pregnant = models.CharField(_("pregnant?"), max_length=3, choices=YesNo.choices, blank=True)
    lactating = models.CharField(_("lactating?"), max_length=3, choices=YesNo.choices, blank=True)
    under_treatment = models.CharField(_("being treated for anything now?"), max_length=255, blank=True)
    recent_surgery = models.CharField(_("recent surgery?"), max_length=255, blank=True)
    medical_comment = models.TextField(_("comment"), blank=True)
    conditions = models.ManyToManyField(
        "patients.MedicalCondition", verbose_name=_("did you ever have?"), blank=True, related_name="+"
    )
    other_condition = models.CharField(_("other disease"), max_length=200, blank=True)
    conditions_comment = models.TextField(_("comments on diseases"), blank=True)
    bp_last_systolic = models.PositiveSmallIntegerField(_("last BP reading - systolic"), null=True, blank=True)
    bp_last_diastolic = models.PositiveSmallIntegerField(_("last BP reading - diastolic"), null=True, blank=True)
    bp_last_when = models.CharField(_("BP - when?"), max_length=60, blank=True)
    bp_drug = models.CharField(_("BP drug"), max_length=120, blank=True)
    bp_clinic_systolic = models.PositiveSmallIntegerField(_("BP in clinic - systolic"), null=True, blank=True)
    bp_clinic_diastolic = models.PositiveSmallIntegerField(_("BP in clinic - diastolic"), null=True, blank=True)
    glucose_level = models.CharField(_("glucose level"), max_length=60, blank=True)
    glucose_last = models.PositiveSmallIntegerField(_("last glucose reading (mg/dl)"), null=True, blank=True)
    glucose_last_when = models.CharField(_("glucose - when?"), max_length=60, blank=True)
    glucose_random_clinic = models.PositiveSmallIntegerField(_("random glucose in clinic (mg/dl)"), null=True, blank=True)
    hba1c = models.DecimalField(_("HbA1c (%)"), max_digits=4, decimal_places=1, null=True, blank=True)
    hba1c_date = models.DateField(_("HbA1c date"), null=True, blank=True)
    allergy_penicillin = models.BooleanField(_("allergic to penicillin"), default=False)
    allergy_sulfa = models.BooleanField(_("allergic to sulfa"), default=False)
    allergy_other = models.CharField(_("other allergy"), max_length=150, blank=True)
    bleeding_or_aspirin = models.CharField(_("prolonged bleeding or taking aspirin?"), max_length=200, blank=True)
    digestion_problem = models.CharField(_("chronic problem with digestion?"), max_length=200, blank=True)
    illegal_drugs = models.BooleanField(_("illegal drugs"), default=False)
    illegal_drugs_notes = models.CharField(_("illegal drugs - details"), max_length=200, blank=True)
    operator_comments = models.TextField(_("operator comments"), blank=True)
    drugs_taken = models.TextField(_("drugs taken by patient"), blank=True, help_text=_("One drug per line."))

    # Dental history
    sensitive_hot_cold = models.BooleanField(_("sensitive to hot or cold"), default=False)
    sensitive_sweets = models.BooleanField(_("sensitive to sweets"), default=False)
    sensitive_biting = models.BooleanField(_("sensitive to biting or chewing"), default=False)
    bruxism = models.CharField(_("clench or grind teeth (awake / sleep)?"), max_length=150, blank=True)
    smoker = models.BooleanField(_("smokes tobacco"), default=False)
    cigarettes_per_day = models.PositiveSmallIntegerField(_("cigarettes per day"), null=True, blank=True)
    mouth_injury = models.CharField(_("serious injury to the mouth?"), max_length=200, blank=True)
    satisfied_appearance = models.CharField(_("satisfied with teeth appearance?"), max_length=200, blank=True)
    cooperation_score = models.PositiveSmallIntegerField(
        _("patient cooperative (0-10)"), null=True, blank=True, validators=[MaxValueValidator(10)]
    )
    implant_willingness_score = models.PositiveSmallIntegerField(
        _("willing for implant treatment (0-10)"), null=True, blank=True, validators=[MaxValueValidator(10)]
    )

    TOOTH_FIELDS = [
        "teeth_carious", "teeth_filled", "teeth_missing", "teeth_not_sure", "teeth_mobility",
        "teeth_hopeless", "teeth_implant_placed", "teeth_implant_failed",
    ]

    class Meta:
        ordering = ["-exam_date", "-pk"]
        verbose_name = _("examination & history")
        verbose_name_plural = _("examinations & histories")

    def __str__(self):
        return f"{self.patient.full_name} - {self.exam_date}"

    def get_absolute_url(self):
        return reverse("charting:exam_detail", args=[self.pk])

    @property
    def is_diabetic(self):
        return self.conditions.filter(name_en__icontains="diabet").exists()

    def alerts(self):
        """Short red flags to show on top of the patient file."""
        items = [str(c) for c in self.conditions.all()]
        if self.other_condition:
            items.append(self.other_condition)
        if self.allergy_penicillin:
            items.append(str(_("Penicillin allergy")))
        if self.allergy_sulfa:
            items.append(str(_("Sulfa allergy")))
        if self.allergy_other:
            items.append(str(_("Allergy: %(what)s") % {"what": self.allergy_other}))
        if self.pregnant == YesNo.YES:
            items.append(str(_("Pregnant")))
        if self.smoker:
            items.append(str(_("Smoker")))
        if self.bleeding_or_aspirin:
            items.append(str(_("Bleeding / aspirin: %(what)s") % {"what": self.bleeding_or_aspirin}))
        return items


class ToothState(models.Model):
    """The current condition of one tooth (the dental chart). Missing rows mean 'sound'."""

    class Status(models.TextChoices):
        PRESENT = "present", _("Natural tooth")
        MISSING = "missing", _("Missing")
        IMPLANT = "implant", _("Implant")
        ROOT_REMNANT = "root_remnant", _("Root remnant")
        IMPACTED = "impacted", _("Impacted")
        PONTIC = "pontic", _("Bridge pontic")

    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.CASCADE, related_name="tooth_states"
    )
    tooth = models.PositiveSmallIntegerField(_("tooth"), choices=TOOTH_CHOICES)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.PRESENT)
    caries = models.BooleanField(_("caries"), default=False)
    caries_surfaces = models.CharField(_("caries surfaces"), max_length=5, blank=True)
    filled = models.BooleanField(_("filled"), default=False)
    filling_surfaces = models.CharField(_("filled surfaces"), max_length=5, blank=True)
    filling_material = models.CharField(_("filling material"), max_length=60, blank=True)
    rct = models.BooleanField(_("root canal treated"), default=False)
    crown = models.BooleanField(_("crown"), default=False)
    crown_material = models.CharField(_("crown material"), max_length=60, blank=True)
    hopeless = models.BooleanField(_("hopeless"), default=False)
    fractured = models.BooleanField(_("fractured"), default=False)
    not_sure = models.BooleanField(_("not sure"), default=False)
    mobility = models.PositiveSmallIntegerField(
        _("mobility grade"), default=0, choices=[(0, "0"), (1, "I"), (2, "II"), (3, "III")]
    )
    implant_site = models.ForeignKey(
        "surgery.SurgerySite", verbose_name=_("implant"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("updated by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    SNAPSHOT_FIELDS = [
        "status", "caries", "caries_surfaces", "filled", "filling_surfaces", "filling_material", "rct",
        "crown", "crown_material", "hopeless", "fractured", "not_sure", "mobility", "implant_site_id",
    ]

    class Meta:
        ordering = ["patient", "tooth"]
        verbose_name = _("tooth condition")
        verbose_name_plural = _("dental chart")
        constraints = [models.UniqueConstraint(fields=["patient", "tooth"], name="unique_tooth_per_patient")]

    def __str__(self):
        return f"{self.tooth}: {self.get_status_display()}"

    def snapshot(self):
        return {name: getattr(self, name) for name in self.SNAPSHOT_FIELDS}


class ToothChange(models.Model):
    """History of every change on the dental chart (who, when, why, before → after)."""

    class Source(models.TextChoices):
        EXAM = "exam", _("Examination")
        TREATMENT = "treatment", _("Treatment")
        SURGERY = "surgery", _("Surgery")
        MANUAL = "manual", _("Edited on the chart")

    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="tooth_changes")
    tooth = models.PositiveSmallIntegerField(_("tooth"), choices=TOOTH_CHOICES)
    changed_at = models.DateTimeField(_("time"), default=timezone.now)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("by"), null=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(_("source"), max_length=20, choices=Source.choices)
    treatment = models.ForeignKey(
        "clinical.TreatmentStep", null=True, blank=True, on_delete=models.SET_NULL, related_name="tooth_changes"
    )
    surgery = models.ForeignKey(
        "surgery.Surgery", null=True, blank=True, on_delete=models.SET_NULL, related_name="tooth_changes"
    )
    examination = models.ForeignKey(
        Examination, null=True, blank=True, on_delete=models.SET_NULL, related_name="tooth_changes"
    )
    summary = models.CharField(_("change"), max_length=255)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)

    class Meta:
        ordering = ["-changed_at", "-pk"]
        verbose_name = _("chart change")
        verbose_name_plural = _("chart history")


class TreatmentPlan(TimeStampedModel):
    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Proposed")
        APPROVED = "approved", _("Approved by supervisor")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    class Difficulty(models.TextChoices):
        SIMPLE = "simple", _("Simple")
        MODERATE = "moderate", _("Moderate")
        ADVANCED = "advanced", _("Advanced (sinus / GBR / block)")

    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.CASCADE, related_name="treatment_plans"
    )
    title = models.CharField(_("plan title"), max_length=150, default=_("Treatment plan"))
    difficulty = models.CharField(
        _("case difficulty"), max_length=20, choices=Difficulty.choices, blank=True, db_index=True
    )
    dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("planned by"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.PROPOSED)
    approved_by = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("approved by"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    OPEN_STATUSES = (Status.PROPOSED, Status.APPROVED)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("treatment plan")
        verbose_name_plural = _("treatment plans")

    def __str__(self):
        return f"{self.title} - {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("charting:plan_detail", args=[self.pk])

    @property
    def progress(self):
        items = [i for i in self.items.all() if i.status != PlanItem.Status.CANCELLED]
        done = sum(1 for i in items if i.status == PlanItem.Status.DONE)
        return done, len(items)


class PlanItem(models.Model):
    class Phase(models.IntegerChoices):
        URGENT = 1, _("1 - Urgent / disease control")
        PREPARATION = 2, _("2 - Preparation (extractions, perio, restorations)")
        SURGICAL = 3, _("3 - Surgical (implants, grafts)")
        PROSTHETIC = 4, _("4 - Prosthetic (impression, delivery)")
        MAINTENANCE = 5, _("5 - Follow-up / maintenance")

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    plan = models.ForeignKey(TreatmentPlan, on_delete=models.CASCADE, related_name="items")
    phase = models.PositiveSmallIntegerField(_("phase"), choices=Phase.choices, default=Phase.PREPARATION)
    step_type = models.ForeignKey("clinical.TreatmentStepType", verbose_name=_("procedure"), on_delete=models.PROTECT)
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    details = models.CharField(_("details"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.PLANNED)
    done_treatment = models.ForeignKey(
        "clinical.TreatmentStep", null=True, blank=True, on_delete=models.SET_NULL, related_name="plan_items"
    )
    done_surgery = models.ForeignKey(
        "surgery.Surgery", null=True, blank=True, on_delete=models.SET_NULL, related_name="plan_items"
    )
    done_at = models.DateTimeField(_("done at"), null=True, blank=True)

    class Meta:
        ordering = ["phase", "pk"]
        verbose_name = _("plan item")
        verbose_name_plural = _("plan items")

    def __str__(self):
        return f"{self.step_type} {self.teeth}".strip()


class PhotoStage(models.TextChoices):
    DIAGNOSTIC = "diagnostic", _("1st visit (diagnostic)")
    SURGERY = "surgery", _("Surgery: simple, moderate, guided")
    SINUS_GBR = "sinus_gbr", _("Sinus lifting and GBR")
    FOLLOW_UP = "follow_up", _("Follow-up after surgery")
    SOFT_TISSUE = "soft_tissue", _("Soft tissue surgery")
    SECOND_STAGE = "second_stage", _("2nd stage surgery")
    IMPRESSION = "impression", _("Impression")
    DELIVERY = "delivery", _("Try-in & delivery")


class PhotoType(LookupModel):
    """One required shot of the CIA photo checklist."""

    stage = models.CharField(_("stage"), max_length=20, choices=PhotoStage.choices)
    optional = models.BooleanField(_("optional"), default=False)

    class Meta(LookupModel.Meta):
        ordering = ["stage", "sort_order"]
        verbose_name = _("photo checklist item")
        verbose_name_plural = _("photo checklist")


def photo_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"patients/{instance.patient_id}/photos/{instance.stage}/{uuid.uuid4().hex}{ext}"


class ClinicalPhoto(TimeStampedModel):
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".avi"}

    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.CASCADE, related_name="clinical_photos"
    )
    stage = models.CharField(_("stage"), max_length=20, choices=PhotoStage.choices)
    photo_type = models.ForeignKey(
        PhotoType, verbose_name=_("shot"), null=True, blank=True, on_delete=models.SET_NULL, related_name="photos"
    )
    surgery = models.ForeignKey(
        "surgery.Surgery", verbose_name=_("surgery"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="photos",
    )
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    file = models.FileField(_("photo / video"), upload_to=photo_path)
    taken_on = models.DateField(_("date"), default=timezone.localdate)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["stage", "photo_type__sort_order", "-taken_on"]
        verbose_name = _("clinical photo")
        verbose_name_plural = _("clinical photos")

    def __str__(self):
        return f"{self.get_stage_display()} - {self.photo_type or ''}"

    @property
    def is_video(self):
        return os.path.splitext(self.file.name)[1].lower() in self.VIDEO_EXTENSIONS
