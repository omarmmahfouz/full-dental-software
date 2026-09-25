import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, LookupModel, TimeStampedModel
from apps.core.utils import age_from_birth_date, parse_egyptian_national_id


class MissingTeeth(models.TextChoices):
    SINGLE = "single", _("Single tooth")
    MULTIPLE = "multiple", _("Multiple teeth")
    FULL_ARCH = "full_arch", _("Full arch")
    BOTH_ARCHES = "both_arches", _("Both arches (full mouth)")
    UNKNOWN = "unknown", _("Not sure")


class Gender(models.TextChoices):
    MALE = "M", _("Male")
    FEMALE = "F", _("Female")


class MaritalStatus(models.TextChoices):
    SINGLE = "single", _("Single")
    MARRIED = "married", _("Married")
    DIVORCED = "divorced", _("Divorced")
    WIDOWED = "widowed", _("Widowed")


class PreferredPhone(models.TextChoices):
    PRIMARY = "primary", _("First mobile")
    SECONDARY = "secondary", _("Second mobile")


class ReferralSource(LookupModel):
    """How the patient heard about us (Facebook, a friend, an existing patient...)."""

    asks_for_patient = models.BooleanField(
        _("ask for the referring patient"),
        default=False,
        help_text=_("Tick for sources like 'referred by a patient' so the secretary links the referring patient."),
    )

    class Meta(LookupModel.Meta):
        verbose_name = _("referral source")
        verbose_name_plural = _("referral sources")


class MedicalCondition(LookupModel):
    """Self-reported (non-professional) medical history items."""

    is_alert = models.BooleanField(
        _("show as alert"), default=True, help_text=_("Highlight in red on the patient file.")
    )

    class Meta(LookupModel.Meta):
        verbose_name = _("medical condition")
        verbose_name_plural = _("medical conditions")


class Lead(TimeStampedModel):
    """An expected patient: someone who called asking to become a patient."""

    class Status(models.TextChoices):
        NEW = "new", _("New")
        FOLLOW_UP = "follow_up", _("Call back later")
        BOOKED = "booked", _("Appointment booked")
        CONVERTED = "converted", _("Became a patient")
        NOT_INTERESTED = "not_interested", _("Not interested")
        UNREACHABLE = "unreachable", _("Unreachable")

    OPEN_STATUSES = (Status.NEW, Status.FOLLOW_UP, Status.BOOKED)

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="leads")
    full_name = models.CharField(_("full name"), max_length=150)
    phone_primary = models.CharField(_("mobile 1"), max_length=20, unique=True)
    phone_secondary = models.CharField(_("mobile 2"), max_length=20, blank=True)
    preferred_phone = models.CharField(
        _("preferred mobile"), max_length=10, choices=PreferredPhone.choices, default=PreferredPhone.PRIMARY
    )
    age = models.PositiveSmallIntegerField(_("age"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=Gender.choices, blank=True)
    city = models.CharField(_("city / area"), max_length=100, blank=True)
    missing_teeth = models.CharField(
        _("missing teeth"), max_length=20, choices=MissingTeeth.choices, default=MissingTeeth.UNKNOWN
    )
    missing_teeth_notes = models.CharField(_("missing teeth details"), max_length=255, blank=True)
    medical_conditions = models.ManyToManyField(
        MedicalCondition, verbose_name=_("medical history (as told by the caller)"), blank=True
    )
    medical_notes = models.TextField(_("other medical notes"), blank=True)
    referral_source = models.ForeignKey(
        ReferralSource, verbose_name=_("how did they hear about us"), null=True, blank=True, on_delete=models.SET_NULL
    )
    referral_notes = models.CharField(_("referral details"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    next_call_at = models.DateTimeField(_("next call"), null=True, blank=True, db_index=True)
    notes = models.TextField(_("notes"), blank=True)
    converted_patient = models.OneToOneField(
        "Patient",
        verbose_name=_("patient file"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_lead",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("expected patient")
        verbose_name_plural = _("expected patients (call list)")

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("patients:lead_detail", args=[self.pk])

    @property
    def preferred_number(self):
        if self.preferred_phone == PreferredPhone.SECONDARY and self.phone_secondary:
            return self.phone_secondary
        return self.phone_primary

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class LeadCall(TimeStampedModel):
    """A call made to / received from an expected patient."""

    class Outcome(models.TextChoices):
        ANSWERED = "answered", _("Answered")
        NO_ANSWER = "no_answer", _("No answer")
        BUSY = "busy", _("Busy / closed")
        WRONG_NUMBER = "wrong_number", _("Wrong number")
        CALL_BACK = "call_back", _("Asked to call back")
        BOOKED = "booked", _("Booked an appointment")

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="calls", verbose_name=_("expected patient"))
    called_at = models.DateTimeField(_("call time"))
    outcome = models.CharField(_("result"), max_length=20, choices=Outcome.choices)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["-called_at"]
        verbose_name = _("call")
        verbose_name_plural = _("calls")


class Patient(TimeStampedModel):
    class IdType(models.TextChoices):
        NATIONAL_ID = "nid", _("Egyptian national ID")
        PASSPORT = "passport", _("Passport")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Under treatment")
        FINISHED = "finished", _("Treatment finished")
        INACTIVE = "inactive", _("Stopped / inactive")

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="patients")
    file_number = models.CharField(_("file number"), max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField(_("full name (as on ID)"), max_length=150, db_index=True)
    id_type = models.CharField(_("ID type"), max_length=10, choices=IdType.choices, default=IdType.NATIONAL_ID)
    national_id = models.CharField(
        _("national ID / passport no."),
        max_length=20,
        unique=True,
        error_messages={"unique": _("A patient with this ID number is already registered.")},
    )
    birth_date = models.DateField(_("date of birth"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=Gender.choices, blank=True)
    marital_status = models.CharField(_("marital status"), max_length=10, choices=MaritalStatus.choices, blank=True)
    phone_primary = models.CharField(
        _("mobile 1 (primary)"),
        max_length=20,
        unique=True,
        error_messages={"unique": _("This mobile number is already registered for another patient.")},
    )
    phone_secondary = models.CharField(_("mobile 2"), max_length=20, blank=True)
    preferred_phone = models.CharField(
        _("preferred mobile"), max_length=10, choices=PreferredPhone.choices, default=PreferredPhone.PRIMARY
    )
    address = models.CharField(_("address"), max_length=255, blank=True)
    city = models.CharField(_("city / area"), max_length=100, blank=True)
    governorate = models.CharField(_("governorate"), max_length=60, blank=True)
    occupation = models.CharField(_("occupation"), max_length=100, blank=True)
    missing_teeth = models.CharField(
        _("missing teeth"), max_length=20, choices=MissingTeeth.choices, default=MissingTeeth.UNKNOWN
    )
    missing_teeth_notes = models.CharField(_("missing teeth details"), max_length=255, blank=True)
    medical_conditions = models.ManyToManyField(
        MedicalCondition, verbose_name=_("medical history (self-reported)"), blank=True
    )
    medical_notes = models.TextField(_("other medical notes"), blank=True)
    referral_source = models.ForeignKey(
        ReferralSource, verbose_name=_("who referred you / how did you hear about us"),
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    referred_by = models.ForeignKey(
        "self", verbose_name=_("referred by patient"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="referred_patients",
    )
    referral_notes = models.CharField(_("referral details"), max_length=255, blank=True)
    assigned_dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("responsible dentist"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_patients",
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("patient")
        verbose_name_plural = _("patients")

    def __str__(self):
        return f"{self.full_name} ({self.file_number})" if self.file_number else self.full_name

    def get_absolute_url(self):
        return reverse("patients:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if self.id_type == self.IdType.NATIONAL_ID and not (self.birth_date and self.gender and self.governorate):
            try:
                data = parse_egyptian_national_id(self.national_id)
            except ValidationError:
                data = None
            if data:
                self.birth_date = self.birth_date or data["birth_date"]
                self.gender = self.gender or data["gender"]
                self.governorate = self.governorate or str(data["governorate"])
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.file_number:
                self.file_number = f"{self.branch.code}-{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(file_number=self.file_number)

    @property
    def age(self):
        return age_from_birth_date(self.birth_date)

    @property
    def preferred_number(self):
        if self.preferred_phone == PreferredPhone.SECONDARY and self.phone_secondary:
            return self.phone_secondary
        return self.phone_primary

    def open_lab_requests(self):
        from apps.clinical.models import LabRequest

        return self.lab_requests.filter(status__in=LabRequest.OPEN_STATUSES)

    def open_complaints(self):
        from apps.complaints.models import Complaint

        return self.complaints.filter(status__in=Complaint.OPEN_STATUSES)

    def relations(self):
        """Relations in both directions as (other_patient, relation_label, relation_obj)."""
        rows = []
        for rel in self.relations_from.select_related("related_patient"):
            rows.append((rel.related_patient, rel.get_relation_display(), rel))
        for rel in self.relations_to.select_related("patient"):
            rows.append((rel.patient, rel.get_relation_display(), rel))
        return rows


def patient_document_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"patients/{instance.patient_id}/{uuid.uuid4().hex}{ext}"


class PatientDocument(TimeStampedModel):
    class Kind(models.TextChoices):
        ID_FRONT = "id_front", _("ID card - front")
        ID_BACK = "id_back", _("ID card - back")
        PASSPORT = "passport", _("Passport")
        CONSENT = "consent", _("Signed consent")
        XRAY = "xray", _("X-ray / CBCT")
        OTHER = "other", _("Other")

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="documents", verbose_name=_("patient"))
    kind = models.CharField(_("document type"), max_length=20, choices=Kind.choices)
    file = models.FileField(_("file"), upload_to=patient_document_path)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["kind", "-created_at"]
        verbose_name = _("patient document")
        verbose_name_plural = _("patient documents")

    def __str__(self):
        return f"{self.get_kind_display()} - {self.patient.full_name}"

    @property
    def is_image(self):
        return os.path.splitext(self.file.name)[1].lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class PatientRelation(TimeStampedModel):
    """Links a patient to a relative or friend who is also our patient."""

    class Relation(models.TextChoices):
        RELATIVE = "relative", _("Relative")
        SPOUSE = "spouse", _("Spouse")
        PARENT_CHILD = "parent_child", _("Parent / child")
        SIBLING = "sibling", _("Brother / sister")
        FRIEND = "friend", _("Friend")
        NEIGHBOUR = "neighbour", _("Neighbour")
        COLLEAGUE = "colleague", _("Work colleague")

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="relations_from", verbose_name=_("patient")
    )
    related_patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="relations_to", verbose_name=_("related patient")
    )
    relation = models.CharField(_("relation"), max_length=20, choices=Relation.choices)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("patient relation")
        verbose_name_plural = _("patient relations")
        constraints = [
            models.UniqueConstraint(fields=["patient", "related_patient"], name="unique_patient_relation"),
            models.CheckConstraint(
                condition=~models.Q(patient=models.F("related_patient")), name="relation_not_self"
            ),
        ]


class CallList(TimeStampedModel):
    """Patients the reception must call, sent by the head of CIA or a supervisor from a
    search (e.g. every plan waiting for guided surgery). The secretaries write each answer."""

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="call_lists")
    title = models.CharField(_("title"), max_length=150)
    message = models.TextField(_("what to tell the patients"), blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("list of patients to call")
        verbose_name_plural = _("lists of patients to call")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("patients:calllist_detail", args=[self.pk])

    @property
    def progress(self):
        entries = list(self.entries.all())
        return sum(1 for e in entries if e.outcome != CallListEntry.Outcome.PENDING), len(entries)


class CallListEntry(models.Model):
    class Outcome(models.TextChoices):
        PENDING = "pending", _("Not called yet")
        BOOKED = "booked", _("Booked an appointment")
        CALL_BACK = "call_back", _("Call again later")
        NOT_INTERESTED = "not_interested", _("Not interested now")
        NO_ANSWER = "no_answer", _("No answer")
        WRONG_NUMBER = "wrong_number", _("Wrong / closed number")

    call_list = models.ForeignKey(CallList, on_delete=models.CASCADE, related_name="entries")
    patient = models.ForeignKey(Patient, verbose_name=_("patient"), on_delete=models.CASCADE, related_name="call_entries")
    reason = models.CharField(_("why"), max_length=255, blank=True)
    outcome = models.CharField(_("result"), max_length=20, choices=Outcome.choices, default=Outcome.PENDING)
    response = models.TextField(_("patient's answer"), blank=True)
    attempts = models.PositiveSmallIntegerField(_("calls made"), default=0)
    called_at = models.DateTimeField(_("last call"), null=True, blank=True)
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("called by"), null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["pk"]
        verbose_name = _("patient to call")
        verbose_name_plural = _("patients to call")
        constraints = [models.UniqueConstraint(fields=["call_list", "patient"], name="unique_patient_per_call_list")]
