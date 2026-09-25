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
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("staff profile")
        verbose_name_plural = _("staff profiles")

    def __str__(self):
        return str(self.user)


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
