from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel


class DentistQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def working_at(self, branch):
        """The dentists who work at a place: those who have it ticked, and those without places
        ticked whose branch it is (or who have no branch, at the default place)."""
        if branch is None:
            return self
        q = models.Q(places=branch) | models.Q(places__isnull=True, branch=branch)
        if branch == Branch.default():
            q |= models.Q(places__isnull=True, branch__isnull=True)
        return self.filter(pk__in=self.model.objects.filter(q).values("pk"))

    def of_kind(self, *kinds):
        return self.filter(kind__in=kinds)


class Dentist(TimeStampedModel):
    """Everyone who treats patients: paying course candidates, training dentists,
    CIA dentists (full or part time) and supervisors (and later the private clinic's
    specialists and freelancers). Patients, room shifts, visits, treatments, surgeries
    and lab requests all point to this record, so each person's work can be followed.

    Only CIA dentists (and later specialists / freelancers) log in. Candidates,
    training dentists and supervisors are chosen by name on the forms."""

    class Kind(models.TextChoices):
        CANDIDATE = "candidate", _("Course candidate")
        TRAINING = "training", _("Training dentist")
        FULLTIME = "fulltime", _("CIA junior dentist (full / part time)")
        SUPERVISOR = "supervisor", _("Supervisor")
        SPECIALIST = "specialist", _("Specialist")
        FREELANCER = "freelancer", _("Freelance dentist")

    class Specialty(models.TextChoices):
        GENERAL = "general", _("General dentist")
        PROSTHODONTIST = "prosthodontist", _("Prosthodontist")
        ENDODONTIST = "endodontist", _("Endodontist")
        ORAL_SURGEON = "oral_surgeon", _("Oral surgeon")
        TMJ = "tmj", _("TMJ specialist (oral surgeon)")
        ORTHODONTIST = "orthodontist", _("Orthodontist")
        PERIODONTIST = "periodontist", _("Periodontist")
        PEDODONTIST = "pedodontist", _("Paediatric dentist")
        IMPLANTOLOGIST = "implantologist", _("Implantologist")
        COSMETIC = "cosmetic", _("Cosmetic dentist")

    full_name = models.CharField(_("full name"), max_length=150, db_index=True)
    name_ar = models.CharField(
        _("name in Arabic"), max_length=150, blank=True,
        help_text=_("e.g. د. منى رفعت — used on the Arabic screens and in the WhatsApp messages to patients."))
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
    places = models.ManyToManyField(
        Branch, verbose_name=_("works at"), blank=True, related_name="place_dentists",
        help_text=_("The places this dentist works in, e.g. CIA and CIC. They are offered on the bookings and "
                    "the room schedule of these places."))
    specialty = models.CharField(_("specialty"), max_length=20, choices=Specialty.choices, blank=True, db_index=True)
    title = models.CharField(
        _("title on printed papers"), max_length=150, blank=True,
        help_text=_("e.g. Consultant of prosthodontics — printed under the name on treatment plans and referrals."))
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    is_active = models.BooleanField(
        _("working now"), default=True, help_text=_("Untick when they leave, so they no longer appear in the lists.")
    )
    show_in_lists = models.BooleanField(
        _("in the drop lists"), default=True,
        help_text=_("Untick for someone who comes rarely: his work stays, he is not offered on the forms. Candidates "
                    "leave the lists by themselves when their course ends."))
    work_time = models.CharField(_("full or part time"), max_length=4, blank=True,
                                 choices=[("full", _("Full time")), ("part", _("Part time"))])
    notes = models.TextField(_("notes"), blank=True)
    signature = models.TextField(
        _("signature"), blank=True, editable=False,
        help_text=_("For a doctor without a login: drawn on his page, printed on his prescriptions and receipts."))

    objects = DentistQuerySet.as_manager()

    class Meta:
        ordering = ["kind", "full_name"]
        verbose_name = _("dentist")
        verbose_name_plural = _("dentists")

    LOGIN_KINDS = (Kind.FULLTIME, Kind.SPECIALIST, Kind.FREELANCER)

    def __str__(self):
        if self.name_ar and (get_language() or "").startswith("ar"):
            return self.name_ar
        return self.full_name

    @property
    def signature_image(self):
        """The drawn signature to print: his own (My signature) when he logs in, else the one drawn on his page."""
        profile = getattr(self.user, "profile", None) if self.user_id else None
        return (profile.signature if profile is not None else "") or self.signature

    @property
    def can_have_login(self):
        return self.kind in self.LOGIN_KINDS

    def get_absolute_url(self):
        return reverse("dentists:detail", args=[self.pk])

    @property
    def label(self):
        """Name with its type (and batch for candidates), or its specialty, for drop-down lists."""
        if self.kind == self.Kind.CANDIDATE and self.candidate_id:
            enrollment = self.candidate.current_enrollment
            if enrollment:
                return f"{self} — {enrollment.course.code}"
        if self.specialty and self.specialty != self.Specialty.GENERAL:
            return f"{self} — {self.get_specialty_display()}"
        return f"{self} — {self.get_kind_display()}"

    @property
    def role_line(self):
        """What is printed under the doctor's name: the title, else the specialty."""
        return self.title or (self.get_specialty_display() if self.specialty else "")

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
