import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    CARD = "card", _("Visa / card")
    INSTAPAY = "instapay", _("InstaPay")
    WALLET = "wallet", _("Mobile wallet (Vodafone Cash...)")
    BANK = "bank", _("Bank transfer")
    BANK_DEPOSIT = "bank_deposit", _("Bank deposit")
    CHEQUE = "cheque", _("Cheque")


class Course(TimeStampedModel):
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="courses")
    name = models.CharField(_("course name"), max_length=150)
    code = models.CharField(_("code / batch"), max_length=30, unique=True)
    start_date = models.DateField(_("start date"), null=True, blank=True)
    end_date = models.DateField(_("end date"), null=True, blank=True)
    fee = models.DecimalField(_("course fee"), max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    capacity = models.PositiveSmallIntegerField(_("capacity"), null=True, blank=True)
    implants_required = models.PositiveSmallIntegerField(
        _("implants each candidate should place"), default=0,
        help_text=_("Used to show how many implants are still remaining for each candidate."),
    )
    is_active = models.BooleanField(_("open"), default=True)
    description = models.TextField(_("description"), blank=True)

    class Meta:
        ordering = ["-start_date", "name"]
        verbose_name = _("course")
        verbose_name_plural = _("courses")

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_absolute_url(self):
        return reverse("academy:course_detail", args=[self.pk])


def candidate_id_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"candidates/{uuid.uuid4().hex}{ext}"


class Candidate(TimeStampedModel):
    """A dentist who pays for an academy course. Their clinical work is recorded on
    the linked ``dentists.Dentist`` record (type "candidate"), so batch, payments,
    implants and cases can all be followed from here."""

    code = models.CharField(
        _("candidate code"), max_length=20, unique=True, null=True, blank=True,
        error_messages={"unique": _("Another candidate already has this code.")},
    )
    full_name = models.CharField(_("full name"), max_length=150, db_index=True)
    certificate_name = models.CharField(
        _("name for certificate (English)"), max_length=150, blank=True,
        help_text=_("First, middle and last name exactly as it should appear on the certificate."),
    )
    birth_date = models.DateField(_("date of birth"), null=True, blank=True)
    nationality = models.CharField(_("nationality"), max_length=60, blank=True)
    national_id = models.CharField(
        _("national ID / passport no."), max_length=20, unique=True, null=True, blank=True,
        error_messages={"unique": _("A candidate with this ID number is already registered.")},
    )
    phone_primary = models.CharField(
        _("mobile 1 (primary)"), max_length=20, unique=True,
        error_messages={"unique": _("This mobile number is already registered for another candidate.")},
    )
    phone_secondary = models.CharField(_("mobile 2"), max_length=20, blank=True)
    whatsapp = models.CharField(_("WhatsApp number"), max_length=20, blank=True)
    email = models.EmailField(_("email"), blank=True)
    facebook = models.CharField(_("Facebook account"), max_length=200, blank=True)
    instagram = models.CharField(_("Instagram account"), max_length=200, blank=True)
    linkedin = models.CharField(_("LinkedIn account"), max_length=200, blank=True)
    referral_source = models.ForeignKey(
        "patients.ReferralSource", verbose_name=_("how did they hear about us"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    university = models.CharField(_("graduated from (university)"), max_length=120, blank=True)
    graduation_year = models.PositiveSmallIntegerField(_("graduation year"), null=True, blank=True)
    syndicate_number = models.CharField(_("syndicate registration no."), max_length=30, blank=True)
    id_scan = models.FileField(_("ID scan"), upload_to=candidate_id_path, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = _("candidate")
        verbose_name_plural = _("candidates")

    @property
    def current_enrollment(self):
        return self.enrollments.select_related("course").order_by("-enrolled_on").first()

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("academy:candidate_detail", args=[self.pk])


class Enrollment(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Studying")
        COMPLETED = "completed", _("Completed")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    candidate = models.ForeignKey(
        Candidate, verbose_name=_("candidate"), on_delete=models.PROTECT, related_name="enrollments"
    )
    course = models.ForeignKey(Course, verbose_name=_("course"), on_delete=models.PROTECT, related_name="enrollments")
    enrolled_on = models.DateField(_("enrollment date"), default=timezone.localdate)
    agreed_fee = models.DecimalField(
        _("agreed fee"), max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    discount = models.DecimalField(
        _("discount"), max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    implants_required_override = models.PositiveSmallIntegerField(
        _("implants required (if different from the course)"), null=True, blank=True
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["-enrolled_on"]
        verbose_name = _("enrollment")
        verbose_name_plural = _("enrollments")
        constraints = [models.UniqueConstraint(fields=["candidate", "course"], name="unique_enrollment")]

    def __str__(self):
        return f"{self.candidate} - {self.course}"

    def get_absolute_url(self):
        return reverse("academy:enrollment_detail", args=[self.pk])

    @property
    def implants_required(self):
        if self.implants_required_override is not None:
            return self.implants_required_override
        return self.course.implants_required

    @property
    def net_fee(self):
        return (self.agreed_fee or Decimal("0")) - (self.discount or Decimal("0"))

    @property
    def total_paid(self):
        return self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def balance(self):
        return self.net_fee - self.total_paid

    def installment_schedule(self, today=None):
        """Installments with how much of each is paid, filling the oldest first."""
        today = today or timezone.localdate()
        remaining = self.total_paid
        rows = []
        for inst in self.installments.order_by("due_date", "number"):
            paid = min(remaining, inst.amount)
            remaining -= paid
            if paid >= inst.amount:
                state = "paid"
            elif inst.due_date < today:
                state = "overdue"
            elif paid > 0:
                state = "partial"
            else:
                state = "due"
            rows.append({"installment": inst, "paid": paid, "remaining": inst.amount - paid, "state": state})
        return rows

    def overdue_amount(self, today=None):
        return sum(
            (row["remaining"] for row in self.installment_schedule(today) if row["state"] == "overdue"),
            Decimal("0"),
        )


class Installment(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveSmallIntegerField(_("installment no."))
    due_date = models.DateField(_("due date"), db_index=True)
    amount = models.DecimalField(_("amount"), max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["due_date", "number"]
        verbose_name = _("installment")
        verbose_name_plural = _("installments")

    def __str__(self):
        return f"#{self.number} {self.due_date} {self.amount}"


class Payment(TimeStampedModel):
    receipt_number = models.CharField(_("receipt number"), max_length=20, unique=True, blank=True, editable=False)
    enrollment = models.ForeignKey(
        Enrollment, verbose_name=_("enrollment"), on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(
        _("amount paid"), max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    paid_on = models.DateField(_("payment date"), default=timezone.localdate, db_index=True)
    method = models.CharField(_("payment method"), max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(
        _("transaction reference"), max_length=100, blank=True,
        help_text=_("Transfer / InstaPay / wallet reference number, if any."),
    )
    proof = models.FileField(
        _("payment scan"), upload_to="candidates/payments/%Y/%m/", blank=True,
        help_text=_("Photo of the transfer / deposit receipt."),
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = _("payment")
        verbose_name_plural = _("payments")

    def __str__(self):
        return f"{self.receipt_number} - {self.amount}"

    def get_absolute_url(self):
        return reverse("academy:payment_receipt", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.receipt_number:
                self.receipt_number = f"RC-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(receipt_number=self.receipt_number)
