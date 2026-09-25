from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel


class DentistQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def of_kind(self, *kinds):
        return self.filter(kind__in=kinds)


class Dentist(TimeStampedModel):
    """Everyone who treats patients: paying course candidates, training dentists,
    full-time dentists and supervisors (and later the private clinic's specialists
    and freelancers). Patients, room shifts, visits, treatments, surgeries and lab
    requests all point to this record, so each person's work can be followed."""

    class Kind(models.TextChoices):
        CANDIDATE = "candidate", _("Course candidate")
        TRAINING = "training", _("Training dentist")
        FULLTIME = "fulltime", _("Full-time dentist")
        SUPERVISOR = "supervisor", _("Supervisor")
        SPECIALIST = "specialist", _("Specialist")
        FREELANCER = "freelancer", _("Freelance dentist")

    full_name = models.CharField(_("full name"), max_length=150, db_index=True)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, db_index=True)
    candidate = models.OneToOneField(
        "academy.Candidate", verbose_name=_("academy candidate file"), null=True, blank=True,
        on_delete=models.CASCADE, related_name="dentist",
        help_text=_("For course candidates: links the dentist to their batch, payments and implant count."),
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name=_("system login"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dentist",
    )
    branch = models.ForeignKey(
        Branch, verbose_name=_("branch"), null=True, blank=True, on_delete=models.SET_NULL, related_name="dentists"
    )
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    is_active = models.BooleanField(
        _("working now"), default=True, help_text=_("Untick when they leave, so they no longer appear in the lists.")
    )
    notes = models.TextField(_("notes"), blank=True)

    objects = DentistQuerySet.as_manager()

    class Meta:
        ordering = ["kind", "full_name"]
        verbose_name = _("dentist")
        verbose_name_plural = _("dentists")

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("dentists:detail", args=[self.pk])

    @property
    def label(self):
        """Name with its type (and batch for candidates), for drop-down lists."""
        if self.kind == self.Kind.CANDIDATE and self.candidate_id:
            enrollment = self.candidate.current_enrollment
            if enrollment:
                return f"{self.full_name} — {enrollment.course.code}"
        return f"{self.full_name} — {self.get_kind_display()}"

    @classmethod
    def for_user(cls, user):
        """The dentist record of the logged-in user (None for non-clinical staff)."""
        if not user or not user.is_authenticated:
            return None
        cached = getattr(user, "_dentist_cache", False)
        if cached is False:
            cached = cls.objects.filter(user=user).select_related("candidate").first()
            user._dentist_cache = cached
        return cached
