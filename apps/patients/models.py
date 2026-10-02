import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, LookupModel, TimeStampedModel
from apps.core.utils import GOVERNORATE_CHOICES, age_from_birth_date, parse_egyptian_national_id


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


# The days and parts of the day a patient prefers for his visits (round 13), kept as "5,0" and "morning,evening".
WEEKDAY_CHOICES = [
    ("5", _("Saturday")), ("6", _("Sunday")), ("0", _("Monday")), ("1", _("Tuesday")),
    ("2", _("Wednesday")), ("3", _("Thursday")), ("4", _("Friday")),
]


class DayPart(models.TextChoices):
    MORNING = "morning", _("Morning (9–12)")
    MIDDAY = "midday", _("Midday (12–3)")
    AFTERNOON = "afternoon", _("Afternoon (3–6)")
    EVENING = "evening", _("Evening (6–9)")

    @classmethod
    def hours(cls, part):
        """The hours (from, to) of a part of the day."""
        return {"morning": (9, 12), "midday": (12, 15), "afternoon": (15, 18), "evening": (18, 21)}[part]


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


class OutReason(LookupModel):
    """Why a patient is labelled out (left, stopped coming, refused the plan...)."""

    class Meta(LookupModel.Meta):
        verbose_name = _("reason for being out")
        verbose_name_plural = _("reasons for being out")


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
    first_call_on = models.DateField(
        _("first called on"), default=timezone.localdate, db_index=True,
        help_text=_("Today by itself. Change it only when typing in older calls."))
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
        ordering = ["first_call_on", "created_at"]
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


class PatientQuerySet(models.QuerySet):
    def here(self):
        """The patients of the place worked in now (every patient outside a page, e.g. in commands).
        A patient belongs to one place; moving to another place opens a new file there (``transfer``)."""
        from apps.core.models import current_place

        place = current_place()
        return self.filter(branch=place) if place is not None else self


class Patient(TimeStampedModel):
    class IdType(models.TextChoices):
        NATIONAL_ID = "nid", _("Egyptian national ID")
        PASSPORT = "passport", _("Passport")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Under treatment")
        FINISHED = "finished", _("Treatment finished")
        INACTIVE = "inactive", _("Stopped / inactive")
        OUT = "out", _("Out")

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="patients")
    file_number = models.CharField(_("file number"), max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField(_("full name (as on ID)"), max_length=150, db_index=True)
    id_type = models.CharField(_("ID type"), max_length=10, choices=IdType.choices, default=IdType.NATIONAL_ID)
    national_id = models.CharField(_("national ID / passport no."), max_length=20, db_index=True)
    birth_date = models.DateField(_("date of birth"), null=True, blank=True)
    gender = models.CharField(_("gender"), max_length=1, choices=Gender.choices, blank=True)
    marital_status = models.CharField(_("marital status"), max_length=10, choices=MaritalStatus.choices, blank=True)
    phone_primary = models.CharField(_("mobile 1 (primary)"), max_length=20, db_index=True)
    phone_secondary = models.CharField(_("mobile 2"), max_length=20, blank=True)
    preferred_phone = models.CharField(
        _("preferred mobile"), max_length=10, choices=PreferredPhone.choices, default=PreferredPhone.PRIMARY
    )
    address = models.CharField(_("address"), max_length=255, blank=True)
    city = models.CharField(_("city / area"), max_length=100, blank=True)
    governorate = models.CharField(_("governorate"), max_length=60, blank=True, choices=GOVERNORATE_CHOICES)
    occupation = models.CharField(_("occupation"), max_length=100, blank=True)
    travel_minutes = models.PositiveSmallIntegerField(
        _("how far he lives (minutes)"), null=True, blank=True,
        help_text=_("About how many minutes the patient takes to come to the clinic."))
    preferred_days = models.CharField(_("days he prefers"), max_length=20, blank=True)
    preferred_times = models.CharField(_("times he prefers"), max_length=40, blank=True)
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
    brought_by = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("the doctor's own patient (brought by)"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="brought_patients",
        help_text=_("A doctor who brought his own patient to the clinic. His work on this patient is paid as his own "
                    "patient (e.g. 40%); every other patient is the clinic's (e.g. 30%)."))
    assigned_dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("responsible dentist"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_patients",
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    out_reason = models.ForeignKey(
        OutReason, verbose_name=_("why out"), null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    out_notes = models.CharField(_("details of why out"), max_length=255, blank=True)
    registered_on = models.DateField(
        _("file opened on"), default=timezone.localdate, db_index=True,
        help_text=_("Today by itself. When typing in old paper files, write the date the file was opened."))
    notes = models.TextField(_("notes"), blank=True)
    transferred_to = models.ForeignKey(
        "self", verbose_name=_("moved to the file"), null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transferred_from", help_text=_("The new file opened when the patient moved to another place."))

    objects = PatientQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("patient")
        verbose_name_plural = _("patients")
        constraints = [
            # One file per person in each place (a person who moves to another place gets a new file there).
            models.UniqueConstraint(fields=["branch", "national_id"], name="patient_one_id_per_place"),
            models.UniqueConstraint(fields=["branch", "phone_primary"], name="patient_one_mobile_per_place"),
        ]

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
                self.governorate = self.governorate or data["governorate_code"]
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.file_number:
                self.file_number = f"{self.branch.badge}-{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(file_number=self.file_number)

    @property
    def age(self):
        return age_from_birth_date(self.birth_date)

    @property
    def preferred_day_list(self):
        """The names of the days he prefers, Saturday first."""
        days = set(self.preferred_days.split(","))
        return [str(label) for code, label in WEEKDAY_CHOICES if code in days]

    @property
    def preferred_time_list(self):
        times = set(self.preferred_times.split(","))
        return [str(label) for code, label in DayPart.choices if code in times]

    def prefers(self, moment):
        """True when a date and time fits the days and times he prefers (or he has no preference)."""
        days = {int(day) for day in self.preferred_days.split(",") if day.isdigit()}
        times = [code for code in self.preferred_times.split(",") if code in DayPart.values]
        if days and moment.weekday() not in days:
            return False
        if times and not any(DayPart.hours(code)[0] <= moment.hour < DayPart.hours(code)[1] for code in times):
            return False
        return True

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

    CARD_KINDS = (Kind.ID_FRONT, Kind.ID_BACK, Kind.PASSPORT)

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="documents", verbose_name=_("patient"))
    kind = models.CharField(_("document type"), max_length=20, choices=Kind.choices)
    file = models.FileField(_("file"), upload_to=patient_document_path, blank=True,
                            help_text=_("A picture or PDF: the X-ray, the CBCT report or a few screenshots of it."))
    location = models.CharField(
        _("where the full scan is kept"), max_length=500, blank=True,
        help_text=_("For a CBCT (DICOM files, too big to upload): the folder on the server or the viewer link "
                    "from the centre, e.g. \\\\CIA-SERVER\\CBCT\\CIA-00020 or https://…"))
    original = models.FileField(_("original scan"), upload_to=patient_document_path, blank=True,
                                help_text=_("The picture as it was uploaded, before the card was cut out."))
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["kind", "-created_at"]
        verbose_name = _("patient document")
        verbose_name_plural = _("patient documents")

    def __str__(self):
        return f"{self.get_kind_display()} - {self.patient.full_name}"

    @property
    def is_image(self):
        return bool(self.file) and os.path.splitext(self.file.name)[1].lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    @property
    def location_is_link(self):
        return self.location.lower().startswith(("http://", "https://"))

    def save(self, *args, **kwargs):
        if self._state.adding and self.kind in self.CARD_KINDS and self.file and not self.original:
            from .idcard import clean_card

            card = clean_card(self.file)
            if card is not None:
                self.original, self.file = self.file.file, card  # keep the uploaded picture as it was
        super().save(*args, **kwargs)


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


def consult_answer_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"patients/{instance.patient_id}/consults/{uuid.uuid4().hex}{ext}"


class MedicalConsult(TimeStampedModel):
    """A letter to the patient's physician before a surgery ("is he fit for it?"): the medical reason (HbA1c above
    7%, a high blood sugar or pressure, another disease), the procedure, the anaesthesia and the medicines after it,
    then the physician's answer. The follow-up of these letters is in medical.py."""

    class Reason(models.TextChoices):
        HBA1C = "hba1c", _("HbA1c above the limit")
        GLUCOSE = "glucose", _("High blood sugar")
        PRESSURE = "pressure", _("High blood pressure")
        HEART = "heart", _("Heart disease")
        BLOOD_THINNER = "blood_thinner", _("Blood thinners")
        BONE_DRUGS = "bone_drugs", _("Bisphosphonates or other bone drugs")
        OTHER = "other", _("Other medical issue")

    class Procedure(models.TextChoices):
        IMPLANTS = "implants", _("Implant placement")
        FULL_ARCH = "full_arch", _("Full arch implants (All-on-X)")
        IMMEDIATE = "immediate", _("Extraction with immediate implants")
        EXTRACTION = "extraction", _("Extraction")
        SINUS = "sinus", _("Sinus lift")
        BONE_GRAFT = "bone_graft", _("Bone graft (GBR / block)")
        SOFT_TISSUE = "soft_tissue", _("Soft tissue graft")
        OTHER = "other", _("Other dental surgery")

    class Bleeding(models.TextChoices):
        MINOR = "minor", _("Minor")
        MODERATE = "moderate", _("Moderate")

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting for the physician's answer")
        ANSWERED = "answered", _("Answered")
        NOT_NEEDED = "not_needed", _("No consultation needed (the dentist's decision)")

    class Answer(models.TextChoices):
        FIT = "fit", _("Fit for the surgery")
        PRECAUTIONS = "precautions", _("Fit, with precautions")
        POSTPONE = "postpone", _("Postpone: control first, then check again")
        NOT_FIT = "not_fit", _("Not fit for the surgery")

    CLEARED = (Answer.FIT, Answer.PRECAUTIONS)
    DEFAULT_ANESTHESIA = "Artinibsa 4% (articaine 4% with epinephrine 1:100,000), local infiltration, 2 to 4 cartridges"
    # The surgery-chart procedure codes each one stands for (to choose the usual medicines, prescriptions/services.py).
    SURGERY_CODES = {
        "implants": {"simple_implant"}, "full_arch": {"simple_implant", "gbr"},
        "immediate": {"extraction", "immediate_implant"}, "extraction": {"extraction"}, "sinus": {"open_sinus"},
        "bone_graft": {"gbr"}, "soft_tissue": {"soft_tissue"},
    }

    patient = models.ForeignKey(Patient, verbose_name=_("patient"), on_delete=models.CASCADE,
                                related_name="medical_consults")
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("dentist"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="medical_consults")
    status = models.CharField(_("status"), max_length=12, choices=Status.choices, default=Status.WAITING,
                              db_index=True)
    reasons = models.CharField(_("why"), max_length=200, blank=True)
    findings = models.TextField(_("medical history and readings"), blank=True,
                                help_text=_("Written in the letter: the diseases, the medicines and the readings."))
    physician = models.CharField(_("to the physician"), max_length=120, blank=True,
                                 help_text=_("The name, if the patient knows it."))
    specialty = models.CharField(_("specialty"), max_length=80, blank=True, default="Internal medicine")
    procedures = models.CharField(_("planned procedure"), max_length=200, blank=True)
    procedure_details = models.CharField(_("details of the procedure"), max_length=255, blank=True,
                                         help_text=_("e.g. 4 implants in the lower jaw with a bone graft"))
    duration = models.CharField(_("expected duration"), max_length=60, blank=True, default="About 1 hour")
    bleeding = models.CharField(_("expected bleeding"), max_length=10, choices=Bleeding.choices,
                                default=Bleeding.MINOR)
    anesthesia = models.CharField(_("anaesthesia"), max_length=200, blank=True, default=DEFAULT_ANESTHESIA)
    medications = models.TextField(_("medicines after the surgery"), blank=True, help_text=_("One per line."))
    question = models.TextField(_("our question"), blank=True)
    sent_on = models.DateField(_("date of the letter"), default=timezone.localdate)
    answer = models.CharField(_("the physician's answer"), max_length=12, choices=Answer.choices, blank=True)
    answer_notes = models.TextField(_("precautions / what the physician wrote"), blank=True)
    answered_by = models.CharField(_("answered by (physician)"), max_length=120, blank=True)
    answered_on = models.DateField(_("answered on"), null=True, blank=True)
    answer_file = models.FileField(_("photo of the answer"), upload_to=consult_answer_path, blank=True)
    recheck_on = models.DateField(_("check again on"), null=True, blank=True,
                                  help_text=_("For a surgery postponed: when to see the patient's readings again."))
    answer_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
                                           on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-sent_on", "-pk"]
        verbose_name = _("medical consultation")
        verbose_name_plural = _("medical consultations")

    def __str__(self):
        return f"{self.patient.full_name} — {self.sent_on:%d/%m/%Y}"

    def get_absolute_url(self):
        return reverse("patients:consult_detail", args=[self.pk])

    @property
    def number(self):
        return f"MC-{self.pk:05d}"

    @property
    def reason_codes(self):
        return [code for code in self.reasons.split(",") if code]

    def reason_labels(self):
        labels = dict(self.Reason.choices)
        return [str(labels[code]) for code in self.reason_codes if code in labels]

    @property
    def procedure_codes(self):
        return [code for code in self.procedures.split(",") if code]

    def procedure_labels(self):
        labels = dict(self.Procedure.choices)
        return [str(labels[code]) for code in self.procedure_codes if code in labels]

    def surgery_codes(self):
        codes = set()
        for code in self.procedure_codes:
            codes |= self.SURGERY_CODES.get(code, set())
        return codes

    def medication_lines(self):
        return [line.strip() for line in self.medications.splitlines() if line.strip()]

    @property
    def is_cleared(self):
        return self.status == self.Status.NOT_NEEDED or (
            self.status == self.Status.ANSWERED and self.answer in self.CLEARED)

    @property
    def days_waiting(self):
        return (timezone.localdate() - self.sent_on).days if self.status == self.Status.WAITING else None
