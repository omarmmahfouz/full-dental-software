from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Adds who/when audit columns to every business record."""

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class LookupModel(models.Model):
    """A bilingual list value editable by the owner in the admin screens."""

    name_ar = models.CharField(_("name (Arabic)"), max_length=120)
    name_en = models.CharField(_("name (English)"), max_length=120, blank=True)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        abstract = True
        ordering = ["sort_order", "name_ar"]

    @property
    def name(self):
        if self.name_en and (get_language() or "").startswith("en"):
            return self.name_en
        return self.name_ar

    def __str__(self):
        return self.name


class Branch(LookupModel):
    """One of the owner's facilities. All data is tagged with its branch so the
    academy, the private clinic and the lab can share one server."""

    class Kind(models.TextChoices):
        ACADEMY = "academy", _("Teaching academy")
        CLINIC = "clinic", _("Private clinic")
        LAB = "lab", _("Dental lab")

    code = models.CharField(
        _("code"), max_length=10, unique=True, help_text=_("Short prefix used in file numbers, e.g. CIA.")
    )
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)

    class Meta(LookupModel.Meta):
        verbose_name = _("branch")
        verbose_name_plural = _("branches")

    @classmethod
    def default(cls):
        branch = cls.objects.filter(code=settings.CLINIC["DEFAULT_BRANCH_CODE"]).first()
        return branch or cls.objects.filter(is_active=True).first()


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile", verbose_name=_("user")
    )
    branch = models.ForeignKey(
        Branch, verbose_name=_("branch"), null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    language = models.CharField(
        _("interface language"), max_length=5, blank=True,
        choices=[("", _("Automatic (Arabic for secretaries, English for dentists)")), ("ar", _("Arabic")), ("en", _("English"))],
    )
    notes = models.TextField(_("notes"), blank=True)
    read_only = models.BooleanField(
        _("read only"), default=False, help_text=_("Can open the pages of their role but cannot save or change anything.")
    )
    access_from = models.DateField(_("access starts on"), null=True, blank=True)
    access_until = models.DateField(_("access ends on"), null=True, blank=True,
                                    help_text=_("After this day the login stops working (e.g. end of a course or contract)."))
    access_days = models.CharField(_("days allowed"), max_length=20, blank=True,
                                   help_text=_("Empty = every day."))
    access_start = models.TimeField(_("from hour"), null=True, blank=True)
    access_end = models.TimeField(_("to hour"), null=True, blank=True)

    WEEKDAYS = [
        ("5", _("Saturday")), ("6", _("Sunday")), ("0", _("Monday")), ("1", _("Tuesday")),
        ("2", _("Wednesday")), ("3", _("Thursday")), ("4", _("Friday")),
    ]

    class Meta:
        verbose_name = _("staff profile")
        verbose_name_plural = _("staff profiles")

    def __str__(self):
        return str(self.user)

    @property
    def has_time_limits(self):
        return bool(self.access_from or self.access_until or self.access_days or self.access_start or self.access_end)

    def access_problem(self, moment=None):
        """Why this person may not use the system right now ("" when they may)."""
        moment = timezone.localtime(moment)
        today, now = moment.date(), moment.time()
        if self.access_from and today < self.access_from:
            return _("Your access starts on %(day)s.") % {"day": self.access_from.strftime("%d/%m/%Y")}
        if self.access_until and today > self.access_until:
            return _("Your access ended on %(day)s.") % {"day": self.access_until.strftime("%d/%m/%Y")}
        if self.access_days and str(today.weekday()) not in self.access_days.split(","):
            return _("You cannot use the system on this day.")
        if self.access_start and self.access_end:
            inside = (self.access_start <= now <= self.access_end if self.access_start <= self.access_end
                      else now >= self.access_start or now <= self.access_end)
            if not inside:
                return _("You can use the system from %(start)s to %(end)s.") % {
                    "start": self.access_start.strftime("%H:%M"), "end": self.access_end.strftime("%H:%M")}
        return ""


class ClinicSettings(models.Model):
    """Options the owner changes from Settings, without touching the code. One row."""

    late_threshold_minutes = models.PositiveSmallIntegerField(
        _("a patient is late after (minutes)"), default=10)
    default_appointment_minutes = models.PositiveSmallIntegerField(_("usual appointment length (minutes)"), default=60)
    complaint_follow_up_days = models.PositiveSmallIntegerField(_("follow up a complaint within (days)"), default=2)
    stock_expiry_days = models.PositiveSmallIntegerField(_("warn about stock expiring within (days)"), default=60)
    reminder_days_before = models.PositiveSmallIntegerField(
        _("send appointment reminders (days before)"), default=1)
    whatsapp_country_code = models.CharField(
        _("country code for WhatsApp"), max_length=4, default="20",
        help_text=_("20 for Egypt. Mobiles written as 010... are sent as 2010..."))

    class Meta:
        verbose_name = _("clinic options")
        verbose_name_plural = _("clinic options")

    def __str__(self):
        return str(_("Clinic options"))

    @classmethod
    def get(cls):
        defaults = {
            "late_threshold_minutes": settings.CLINIC.get("LATE_THRESHOLD_MINUTES", 10),
            "default_appointment_minutes": settings.CLINIC.get("DEFAULT_APPOINTMENT_MINUTES", 60),
            "complaint_follow_up_days": settings.CLINIC.get("COMPLAINT_FOLLOW_UP_DAYS", 2),
        }
        return cls.objects.get_or_create(pk=1, defaults=defaults)[0]


class AreaAccess(models.Model):
    """Limit a role in one part of the system: read only, or hidden.
    Without a row the role keeps the access it normally has."""

    class Level(models.TextChoices):
        FULL = "full", _("Normal access")
        READ = "read", _("Read only")
        HIDDEN = "hidden", _("No access")

    role = models.CharField(_("role"), max_length=20)
    area = models.CharField(_("part of the system"), max_length=30)
    level = models.CharField(_("access"), max_length=10, choices=Level.choices, default=Level.FULL)

    class Meta:
        verbose_name = _("access of a role")
        verbose_name_plural = _("access of the roles")
        constraints = [models.UniqueConstraint(fields=["role", "area"], name="unique_area_access")]

    def __str__(self):
        return f"{self.role} / {self.area}: {self.level}"


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")
        DANGER = "danger", _("Urgent")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications", verbose_name=_("recipient")
    )
    title = models.CharField(_("title"), max_length=200)
    message = models.TextField(_("message"), blank=True)
    url = models.CharField(_("link"), max_length=300, blank=True)
    level = models.CharField(_("level"), max_length=10, choices=Level.choices, default=Level.INFO)
    created_at = models.DateTimeField(_("created at"), default=timezone.now, db_index=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")

    def __str__(self):
        return self.title

    @property
    def is_read(self):
        return self.read_at is not None


def branch_for_user(user):
    """The branch a staff member works in (falls back to the default branch)."""
    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    if profile is not None and profile.branch_id:
        return profile.branch
    return Branch.default()
