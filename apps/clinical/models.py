from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, LookupModel, TimeStampedModel


class TreatmentStepType(LookupModel):
    class Meta(LookupModel.Meta):
        verbose_name = _("treatment step type")
        verbose_name_plural = _("treatment step types")


class TreatmentStep(TimeStampedModel):
    """One clinical step done by an intern (so every intern's work can be followed)."""

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
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("done by (intern)"), on_delete=models.PROTECT,
        related_name="treatment_steps",
    )
    supervised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("supervisor present"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
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

    @property
    def is_verified(self):
        return self.verified_at is not None


class Lab(models.Model):
    name = models.CharField(_("name"), max_length=120, unique=True)
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
        return self.name


class LabWorkType(LookupModel):
    class Meta(LookupModel.Meta):
        verbose_name = _("lab work type")
        verbose_name_plural = _("lab work types")


class LabRequest(TimeStampedModel):
    """A lab prescription and its journey: reviewed → sent → received → delivered."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_REVIEW = "pending_review", _("Waiting for supervisor review")
        APPROVED = "approved", _("Reviewed - ready to send")
        SENT = "sent", _("At the lab")
        RECEIVED = "received", _("Received from lab")
        DELIVERED = "delivered", _("Delivered to patient")
        CANCELLED = "cancelled", _("Cancelled")

    OPEN_STATUSES = (Status.DRAFT, Status.PENDING_REVIEW, Status.APPROVED, Status.SENT, Status.RECEIVED)

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
    shade = models.CharField(_("shade"), max_length=30, blank=True)
    material = models.CharField(_("material"), max_length=100, blank=True)
    instructions = models.TextField(_("instructions to the lab"), blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("requested by (doctor)"), on_delete=models.PROTECT,
        related_name="lab_requests",
    )
    due_date = models.DateField(_("needed back by"), null=True, blank=True)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("reviewed by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
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
