from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, ClinicSettings, TimeStampedModel


class Complaint(TimeStampedModel):
    class Category(models.TextChoices):
        WAITING = "waiting", _("Waiting time / delay")
        TREATMENT = "treatment", _("Treatment result")
        PAIN = "pain", _("Pain / problem after treatment")
        STAFF = "staff", _("Staff behaviour")
        DOCTOR = "doctor", _("Doctor behaviour")
        BILLING = "billing", _("Payment / prices")
        CLEANLINESS = "cleanliness", _("Cleanliness")
        LAB = "lab", _("Lab work")
        APPOINTMENT = "appointment", _("Appointments")
        OTHER = "other", _("Other")

    class Severity(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High - urgent")

    class Status(models.TextChoices):
        OPEN = "open", _("New")
        IN_PROGRESS = "in_progress", _("Being followed up")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")

    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    number = models.CharField(_("complaint number"), max_length=20, unique=True, blank=True, editable=False)
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="complaints")
    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT, related_name="complaints"
    )
    category = models.CharField(_("category"), max_length=20, choices=Category.choices)
    severity = models.CharField(_("severity"), max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    description = models.TextField(_("complaint (in the patient's words)"))
    concerned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("concerned staff member"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="complaints_about",
    )
    concerned_dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("concerned dentist"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="complaints_about",
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("followed up by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_complaints",
    )
    follow_up_due = models.DateField(_("next follow-up date"), null=True, blank=True)
    resolution = models.TextField(_("how it was solved"), blank=True)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("resolved by"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("complaint")
        verbose_name_plural = _("complaints")

    def __str__(self):
        return f"{self.number} - {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("complaints:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.pk and not self.follow_up_due:
            self.follow_up_due = timezone.localdate() + timedelta(days=ClinicSettings.get().complaint_follow_up_days)
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"CMP-{self.pk:05d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_overdue(self):
        return self.is_open and self.follow_up_due is not None and self.follow_up_due < timezone.localdate()


class ComplaintFollowUp(TimeStampedModel):
    class Action(models.TextChoices):
        CALLED_PATIENT = "called", _("Called the patient")
        MET_PATIENT = "met", _("Met the patient")
        SPOKE_TO_STAFF = "staff", _("Spoke to the doctor / staff")
        RE_TREATMENT = "retreat", _("Booked a correction visit")
        REFUND = "refund", _("Refund / discount")
        NOTE = "note", _("Note")

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="follow_ups")
    action = models.CharField(_("action taken"), max_length=20, choices=Action.choices, default=Action.NOTE)
    note = models.TextField(_("details"))
    new_status = models.CharField(_("status after this step"), max_length=20, choices=Complaint.Status.choices)
    next_follow_up = models.DateField(_("next follow-up date"), null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = _("follow-up")
        verbose_name_plural = _("follow-ups")
