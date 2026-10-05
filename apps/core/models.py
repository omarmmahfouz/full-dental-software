from contextlib import contextmanager
from contextvars import ContextVar
from datetime import time

from django.conf import settings
from django.core.validators import RegexValidator
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
    has_cbct = models.BooleanField(
        _("has a CBCT machine"), default=False,
        help_text=_("A CBCT asked by a dentist here can then be marked as done in the clinic."))

    class Theme(models.TextChoices):
        STANDARD = "standard", _("Standard (light)")
        ELITE = "elite", _("Elite (navy and gold)")

    # The look of the place and its printed papers (bills, plans, lab requests, receipts).
    file_prefix = models.CharField(
        _("file number prefix"), max_length=10, blank=True,
        help_text=_("Empty = the code. e.g. EK gives the new files EK-00001."))
    tagline = models.CharField(_("line under the name"), max_length=150, blank=True,
                               help_text=_("Printed under the name, e.g. Specialist dental care."))
    email = models.EmailField(_("e-mail"), blank=True)
    theme = models.CharField(_("look of the screens"), max_length=10, choices=Theme.choices, default=Theme.STANDARD,
                             help_text=_("The top bar, the buttons and the printed papers of this place."))
    color = models.CharField(_("colour"), max_length=7, blank=True,
                             validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", _("Write the colour as # and 6 letters "
                                                                               "or digits, e.g. #1F6FB2."))],
                             help_text=_("e.g. #1F6FB2. Empty = the usual colour of the place."))
    logo = models.ImageField(_("logo"), upload_to="places/", blank=True,
                             help_text=_("On the top bar, the login page and the printed papers of this place."))
    # Hours and rooms
    opens_at = models.TimeField(_("opens at"), null=True, blank=True,
                                help_text=_("Empty = the hours in the clinic options."))
    closes_at = models.TimeField(_("closes at"), null=True, blank=True)
    closed_days = models.CharField(_("closed on"), max_length=20, blank=True,
                                   help_text=_("The days the place is closed: no free times are offered on them."))
    rooms_shared = models.BooleanField(
        _("rooms are shared"), default=False,
        help_text=_("Any doctor works in any free room: bookings need no room schedule, the room is chosen by "
                    "itself and can be changed in one click."))

    class Meta(LookupModel.Meta):
        verbose_name = _("branch")
        verbose_name_plural = _("branches")

    @classmethod
    def default(cls):
        branch = cls.objects.filter(code=settings.CLINIC["DEFAULT_BRANCH_CODE"]).first()
        return branch or cls.objects.filter(is_active=True).first()

    @property
    def badge(self):
        """The short label of the place on badges and the place switch (EK, CIC...)."""
        return self.file_prefix or self.code

    @property
    def is_elite(self):
        return self.theme == self.Theme.ELITE

    @property
    def closed_weekdays(self):
        return {int(day) for day in self.closed_days.split(",") if day.strip().isdigit()}

    def hours(self):
        """(opens, closes) of the place: its own hours, else those of the clinic options."""
        options = ClinicSettings.get()
        return self.opens_at or options.day_start, self.closes_at or options.day_end

    # The places' own marks, until a logo is uploaded in Settings → Places.
    MARKS = {"PVT": "img/khadem-mark.svg", "CIC": "img/cic-logo.jpg", "LAB": "img/gdil-logo.jpg"}

    @property
    def has_mark(self):
        """True when the place has a logo of its own (uploaded, or one of the marks above)."""
        return bool(self.logo) or self.code in self.MARKS

    @property
    def mark_url(self):
        """The logo shown on the top bar and the login page: the one uploaded, else the place's own mark."""
        from django.templatetags.static import static
        from django.urls import reverse

        if self.logo:
            return reverse("core:place_logo", args=[self.code])
        return static(self.MARKS.get(self.code, "img/cia-mark.png"))


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile", verbose_name=_("user")
    )
    branch = models.ForeignKey(
        Branch, verbose_name=_("branch"), null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    places = models.ManyToManyField(
        Branch, verbose_name=_("works at"), blank=True, related_name="staff_places",
        help_text=_("The places this person works in. With more than one, a switch in the top bar chooses the "
                    "place they work in now."))
    phone = models.CharField(_("mobile"), max_length=20, blank=True)
    language = models.CharField(
        _("interface language"), max_length=5, blank=True,
        choices=[("", _("Automatic (Arabic for secretaries, English for dentists)")), ("ar", _("Arabic")), ("en", _("English"))],
    )
    notes = models.TextField(_("notes"), blank=True)
    show_hints = models.BooleanField(
        _("show hints"), default=True, help_text=_("A short tip at the top of each page on what to do there."))
    signature = models.TextField(
        _("signature"), blank=True, editable=False,
        help_text=_("Drawn once on the screen (user menu → My signature): printed on receipts and prescriptions."))
    read_only = models.BooleanField(
        _("read only"), default=False, help_text=_("Can open the pages of their role but cannot save or change anything.")
    )
    must_change_password = models.BooleanField(
        _("must choose a new password"), default=False,
        help_text=_("Set when the owner gives a temporary password: the person chooses their own at the next login."))
    weak_password = models.BooleanField(
        _("easy password"), default=False, editable=False,
        help_text=_("Seen at the last login: the password is short, common or like the username (security.py)."))
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


# While a page is being made, the clinic options are read from the database once and kept here
# (a report of thousands of visits asks "is this visit late?" for each one).
_page_cache = ContextVar("clinic_page_cache", default=None)


@contextmanager
def page_cache():
    """Keep the clinic options for one page (see ``PageCacheMiddleware``)."""
    token = _page_cache.set({})
    try:
        yield
    finally:
        _page_cache.reset(token)


# The place the person making the page works in now (set by WorkingPlaceMiddleware). Patients belong to one
# place: searches, lookups and lists use it, so a place never sees the names of another place's patients.
_current_place = ContextVar("current_place", default=None)


@contextmanager
def working_at(place):
    token = _current_place.set(place)
    try:
        yield
    finally:
        _current_place.reset(token)


def current_place():
    """The place worked in now, or None outside a page (commands, the nightly tasks)."""
    return _current_place.get()


def reception_default():
    """What the reception sees in a patient's file until the owner changes it: the lab work to receive, the CBCT and
    tests to send the patient for, and the instructions to print."""
    return ["lab", "tests", "instructions"]


class ClinicSettings(models.Model):
    """Options the owner changes from Settings, without touching the code. One row."""

    late_threshold_minutes = models.PositiveSmallIntegerField(
        _("a patient is late after (minutes)"), default=10)
    default_appointment_minutes = models.PositiveSmallIntegerField(_("usual appointment length (minutes)"), default=30)
    day_start = models.TimeField(_("appointments start at"), default=time(9))
    day_end = models.TimeField(_("appointments end at"), default=time(17))
    surgery_days = models.CharField(
        _("usual surgery days"), max_length=20, blank=True, default="3,4",
        help_text=_("A new shift on these days is a surgery day unless you change it."))
    complaint_follow_up_days = models.PositiveSmallIntegerField(_("follow up a complaint within (days)"), default=2)
    stock_expiry_days = models.PositiveSmallIntegerField(_("warn about stock expiring within (days)"), default=60)
    reminder_days_before = models.PositiveSmallIntegerField(
        _("send appointment reminders (days before)"), default=1)
    whatsapp_country_code = models.CharField(
        _("country code for WhatsApp"), max_length=4, default="20",
        help_text=_("20 for Egypt. Mobiles written as 010... are sent as 2010..."))
    dicom_email = models.EmailField(
        _("e-mail for CBCT files"), blank=True, default="ciapts@gmail.com",
        help_text=_("Printed on CBCT requests: the centre sends the DICOM files here."))
    fawry_fee_percent = models.DecimalField(
        _("Fawry percentage on card payments (%)"), max_digits=5, decimal_places=2, default=0,
        help_text=_("What Fawry keeps from each payment taken on its machine, e.g. 1.5. Each move can still be corrected."))
    # The parts of a patient's file the reception sees (apps/patients/access.py FILE_PARTS); dentists see them all.
    reception_sees = models.JSONField(_("the reception sees in a patient's file"), default=reception_default,
                                      blank=True)
    # A reading above these puts the patient on the medical follow-up (apps/patients/medical.py).
    hba1c_limit = models.DecimalField(_("HbA1c above (%) needs a physician's opinion"), max_digits=4,
                                      decimal_places=1, default=7)
    glucose_limit = models.PositiveSmallIntegerField(
        _("random blood sugar above (mg/dl) needs a physician's opinion"), default=200)
    systolic_limit = models.PositiveSmallIntegerField(
        _("blood pressure from (systolic, mmHg) needs a physician's opinion"), default=160)
    diastolic_limit = models.PositiveSmallIntegerField(
        _("blood pressure from (diastolic, mmHg) needs a physician's opinion"), default=100)
    # The visit after a surgery (apps/surgery/followup.py).
    follow_up_sinus_days = models.PositiveSmallIntegerField(_("check after a sinus lift (days)"), default=2)
    follow_up_graft_days = models.PositiveSmallIntegerField(_("check after a bone or gum graft (days)"), default=7)
    follow_up_days = models.PositiveSmallIntegerField(_("suture removal after other surgeries (days)"), default=7)
    # Security (apps/core/security.py).
    idle_logout_minutes = models.PositiveSmallIntegerField(
        _("log out after (minutes without use)"), default=60,
        help_text=_("A PC left open closes its session by itself. 0 = never."))
    force_strong_passwords = models.BooleanField(
        _("people with an easy password must change it"), default=False,
        help_text=_("At their next login, people whose password is short, common or like their username choose a "
                    "new one."))
    one_device_per_login = models.BooleanField(
        _("one device per login"), default=True,
        help_text=_("A login opened on a second PC or tablet logs out the first one (it is told why)."))

    class Meta:
        verbose_name = _("clinic options")
        verbose_name_plural = _("clinic options")

    def __str__(self):
        return str(_("Clinic options"))

    @property
    def surgery_weekdays(self):
        return {int(day) for day in self.surgery_days.split(",") if day.strip().isdigit()}

    @classmethod
    def get(cls):
        defaults = {
            "late_threshold_minutes": settings.CLINIC.get("LATE_THRESHOLD_MINUTES", 10),
            "default_appointment_minutes": settings.CLINIC.get("DEFAULT_APPOINTMENT_MINUTES", 30),
            "complaint_follow_up_days": settings.CLINIC.get("COMPLAINT_FOLLOW_UP_DAYS", 2),
        }
        cache = _page_cache.get()
        if cache is not None and "options" in cache:
            return cache["options"]
        options = cls.objects.get_or_create(pk=1, defaults=defaults)[0]
        if cache is not None:
            cache["options"] = options
        return options

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache = _page_cache.get()
        if cache is not None:
            cache.pop("options", None)


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


class PersonAreaAccess(models.Model):
    """One person's access to one part of the system, instead of what their roles give there,
    e.g. only some secretaries work with the academy. It never goes beyond what the role allows."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="area_access")
    area = models.CharField(_("part of the system"), max_length=30)
    level = models.CharField(_("access"), max_length=10, choices=AreaAccess.Level.choices)

    class Meta:
        verbose_name = _("access of a person")
        verbose_name_plural = _("access of people")
        constraints = [models.UniqueConstraint(fields=["user", "area"], name="unique_person_area_access")]

    def __str__(self):
        return f"{self.user} / {self.area}: {self.level}"


class ChangeRequest(models.Model):
    """A change the reception asked for (patient data, a visit's times) that waits for the head
    of CIA. Nothing changes until it is approved; every request is kept."""

    class Kind(models.TextChoices):
        PATIENT = "patient", _("Patient data")
        VISIT_TIMES = "visit_times", _("Visit times")
        OPERATOR = "operator", _("Operator of a treatment or surgery")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    kind = models.CharField(_("change of"), max_length=20, choices=Kind.choices)
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+", help_text=_("Where it was asked: the heads of that place approve it."))
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    title = models.CharField(_("record"), max_length=200)
    changes = models.JSONField(_("changes"), default=list)  # [{"field", "label", "old", "new", "value"}]
    reason = models.CharField(_("why"), max_length=255, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("asked by"), null=True,
                                     on_delete=models.SET_NULL, related_name="+")
    requested_at = models.DateTimeField(_("asked at"), default=timezone.now)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("decided by"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(_("decided at"), null=True, blank=True)
    decision_note = models.CharField(_("note"), max_length=255, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = _("change waiting for approval")
        verbose_name_plural = _("changes waiting for approval")
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"

    @property
    def target(self):
        return self.content_type.get_object_for_this_type(pk=self.object_id)


class ProblemReport(models.Model):
    """Something that went wrong in the software: told by a person ("Report a problem"), or
    recorded by itself when a page fails. The owner reads them and passes them to whoever
    maintains the software."""

    class Kind(models.TextChoices):
        REPORTED = "reported", _("Told by a user")
        AUTOMATIC = "automatic", _("Page error (recorded automatically)")

    class Status(models.TextChoices):
        NEW = "new", _("New")
        SEEN = "seen", _("Being looked at")
        SOLVED = "solved", _("Solved")

    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices, default=Kind.REPORTED)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    page = models.CharField(_("page"), max_length=500, blank=True)
    description = models.TextField(_("what happened"), blank=True)
    screenshot = models.FileField(_("screenshot or photo"), upload_to="problems/%Y/%m/", blank=True)
    video = models.FileField(_("video of the screen"), upload_to="problems/%Y/%m/", blank=True,
                             help_text=_("Recorded on the screen while the problem happens, or filmed with a phone."))
    error = models.TextField(_("technical details"), blank=True)
    signature = models.CharField(max_length=64, blank=True, db_index=True)  # the same page error is counted, not repeated
    times = models.PositiveIntegerField(_("times"), default=1)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("reported by"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(_("date"), default=timezone.now)
    last_seen_at = models.DateTimeField(_("last time"), default=timezone.now)
    answer = models.TextField(_("answer / what was done"), blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("handled by"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-last_seen_at"]
        verbose_name = _("problem report")
        verbose_name_plural = _("problem reports")

    def __str__(self):
        return f"{self.get_kind_display()}: {self.page}"


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
        indexes = [models.Index(fields=["recipient", "read_at"], name="notification_unread")]

    def __str__(self):
        return self.title

    @property
    def is_read(self):
        return self.read_at is not None


class BackupRun(models.Model):
    """One run of the backup: the data (a ZIP of all records) or the photo copy (only the new files).
    The owner's home page warns when the last good one is too old or the last one failed."""

    class Kind(models.TextChoices):
        DATABASE = "database", _("All the data (ZIP)")
        FILES = "files", _("Copy of the photos and files")

    kind = models.CharField(_("backup of"), max_length=10, choices=Kind.choices)
    started_at = models.DateTimeField(_("started at"), default=timezone.now)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)
    ok = models.BooleanField(_("done without errors"), default=False)
    where = models.CharField(_("saved in"), max_length=500, blank=True)
    size = models.BigIntegerField(_("size (bytes)"), default=0)
    files_copied = models.PositiveIntegerField(_("files copied"), default=0)
    files_checked = models.PositiveIntegerField(_("files checked"), default=0)
    error = models.TextField(_("error"), blank=True)
    # Round 11: each ZIP is opened again and checked, and copied to a second place (backup.py).
    verified = models.BooleanField(_("checked after saving"), default=False)
    records = models.PositiveIntegerField(_("records in it"), default=0)
    copy_where = models.CharField(_("second copy in"), max_length=500, blank=True)
    copy_error = models.CharField(_("second copy problem"), max_length=500, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = _("backup run")
        verbose_name_plural = _("backup runs")

    def __str__(self):
        return f"{self.get_kind_display()} {timezone.localtime(self.started_at):%d/%m/%Y %H:%M}"


def branch_for_user(user):
    """The place a staff member works in now: the one chosen with the switch in the top bar
    (see WorkingPlaceMiddleware), else their own branch, else the default branch."""
    working = getattr(user, "_working_branch", None) if user is not None else None
    if working is not None:
        return working
    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    if profile is not None and profile.branch_id:
        return profile.branch
    return Branch.default()


def staff_at(place, *roles):
    """The active people with one of ``roles`` who work at ``place`` (their own place or one ticked)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    users = get_user_model().objects.filter(is_active=True, groups__name__in=roles)
    if place is not None:
        here = Q(profile__branch=place) | Q(profile__places=place)
        if place == Branch.default():  # people without a place of their own work at the main place
            here |= Q(profile__isnull=True) | Q(profile__branch__isnull=True)
        users = users.filter(here)
    return users.distinct()


def working_places(user):
    """The places (not the lab) this person can work in: all of them for the owner, else the
    places ticked on their profile and their own branch."""
    from .roles import OWNER, user_roles

    places = Branch.objects.filter(is_active=True).exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")
    if user is None or not user.is_authenticated:
        return places.none()
    if user.is_superuser or OWNER in user_roles(user):
        return places
    profile = getattr(user, "profile", None)
    if profile is None:
        return places.filter(pk=getattr(Branch.default(), "pk", None))
    ids = set(profile.places.values_list("pk", flat=True))
    ids.add(profile.branch_id or getattr(Branch.default(), "pk", None))
    return places.filter(pk__in=ids)


def switch_places(user):
    """The places this person can open (the switch in the top bar and the login page): their clinics, and the dental
    lab for the lab's staff and the owner. Kept on the person for the page."""
    if user is None or not user.is_authenticated:
        return []
    cached = getattr(user, "_switch_places", None)
    if cached is None:
        from .roles import LAB_STAFF, has_role

        cached = list(working_places(user))
        if user.is_superuser or has_role(user, *LAB_STAFF):
            cached += list(Branch.objects.filter(is_active=True, kind=Branch.Kind.LAB).order_by("sort_order", "pk"))
        user._switch_places = cached
    return cached


class PasswordHelp(models.Model):
    """Someone who forgot the password asks from the login page; the owner gives a temporary password (Settings →
    Users). There is no e-mail: the clinic works on its own network."""

    class Status(models.TextChoices):
        NEW = "new", _("Waiting")
        DONE = "done", _("New password given")
        REFUSED = "refused", _("Refused")

    username = models.CharField(_("username written"), max_length=150)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("person"), null=True, blank=True,
                             on_delete=models.CASCADE, related_name="password_requests")
    note = models.CharField(_("note"), max_length=200, blank=True)
    asked_at = models.DateTimeField(_("asked at"), default=timezone.now)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.NEW)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("done by"), null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    done_at = models.DateTimeField(_("done at"), null=True, blank=True)

    class Meta:
        ordering = ["-asked_at"]
        verbose_name = _("forgotten password")
        verbose_name_plural = _("forgotten passwords")

    def __str__(self):
        return self.username


class SecurityEvent(models.Model):
    """The security log (apps/core/security.py): logins and wrong passwords, logins closed after too many wrong
    passwords, log outs, passwords changed or given, data taken out of the system, pages refused, and visits from
    outside the clinic's network. Kept a year; the owner reads it in Settings → Security."""

    class Kind(models.TextChoices):
        LOGIN = "login", _("Logged in")
        LOGIN_FAILED = "login_failed", _("Wrong password")
        LOCKED = "locked", _("Login closed after wrong passwords")
        UNLOCKED = "unlocked", _("Login opened again by the owner")
        LOGOUT = "logout", _("Logged out")
        IDLE_LOGOUT = "idle_logout", _("Logged out after no use")
        FORCED_LOGOUT = "forced_logout", _("Logged out by the owner")
        REPLACED = "replaced", _("Logged out: the same login opened on another device")
        PASSWORD_CHANGED = "password_changed", _("Password changed")
        PASSWORD_GIVEN = "password_given", _("Password set by the owner")
        EXPORT = "export", _("Data taken out (file, export or backup)")
        DENIED = "denied", _("Page refused (no permission)")
        OUTSIDE = "outside", _("Refused: from outside the clinic's network")

    ALERTS = (Kind.LOCKED, Kind.OUTSIDE)

    kind = models.CharField(_("what"), max_length=20, choices=Kind.choices, db_index=True)
    at = models.DateTimeField(_("when"), default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("person"), null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="+")
    username = models.CharField(_("username"), max_length=150, blank=True, db_index=True)
    ip = models.GenericIPAddressField(_("device address (IP)"), null=True, blank=True, db_index=True)
    device = models.CharField(_("browser"), max_length=200, blank=True)
    path = models.CharField(_("page"), max_length=300, blank=True)
    details = models.CharField(_("details"), max_length=300, blank=True)
    session = models.CharField(_("session"), max_length=64, blank=True, db_index=True, editable=False,
                               help_text=_("A fingerprint of a session closed because the login was opened on "
                                           "another device: that device is told why."))

    class Meta:
        ordering = ["-at", "-pk"]
        verbose_name = _("security event")
        verbose_name_plural = _("security log")

    def __str__(self):
        return f"{self.get_kind_display()} {self.username} {timezone.localtime(self.at):%d/%m/%Y %H:%M}"


class DeletedRecord(models.Model):
    """A record deleted from the system, kept with everything it held, who deleted it and when (security.py): a
    mistake can be seen and typed back. Kept a year."""

    model = models.CharField(_("kind of record"), max_length=100, db_index=True)
    label = models.CharField(_("record"), max_length=300)
    object_id = models.CharField(_("number"), max_length=40)
    data = models.JSONField(_("what it held"), default=dict)
    deleted_at = models.DateTimeField(_("deleted at"), default=timezone.now, db_index=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("deleted by"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    page = models.CharField(_("page"), max_length=300, blank=True)

    class Meta:
        ordering = ["-deleted_at", "-pk"]
        verbose_name = _("deleted record")
        verbose_name_plural = _("deleted records")

    def __str__(self):
        return f"{self.kind_name}: {self.label}"

    @property
    def kind_name(self):
        """The kind of record in the reader's language (``model`` keeps the program's name, e.g. "patients.patient")."""
        from django.apps import apps

        try:
            return apps.get_model(self.model)._meta.verbose_name
        except (LookupError, ValueError):
            return self.model


class WorkSession(models.Model):
    """One stretch of time a person had the system open (round 14, core/worktime.py): from the first page after
    logging in to logging out, being logged out for no use, or 30 minutes without any sign (the page closed). "Open"
    is the whole stretch; "worked" adds up the moments of use (pages opened, typing or tapping on a page)."""

    class End(models.TextChoices):
        LOGOUT = "logout", _("logged out")
        IDLE = "idle", _("logged out for no use")
        CLOSED = "closed", _("closed the page")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("person"), on_delete=models.CASCADE,
                             related_name="work_sessions")
    branch = models.ForeignKey(Branch, verbose_name=_("place"), null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+")
    started_at = models.DateTimeField(_("opened at"), default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(_("last seen open"), default=timezone.now)
    last_active_at = models.DateTimeField(_("last used"), default=timezone.now)
    active_seconds = models.PositiveIntegerField(_("worked (seconds)"), default=0)
    pages = models.PositiveIntegerField(_("pages opened"), default=0)
    ended_at = models.DateTimeField(_("ended at"), null=True, blank=True)
    end = models.CharField(_("how it ended"), max_length=10, choices=End.choices, blank=True)
    device = models.CharField(_("device"), max_length=120, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = _("time in the system")
        verbose_name_plural = _("time in the system")

    def __str__(self):
        return f"{self.user} {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def finished_at(self):
        return self.ended_at or self.last_seen_at

    @property
    def open_seconds(self):
        return max(0, int((self.finished_at - self.started_at).total_seconds()))

    @property
    def worked_share(self):
        """The part of the open time spent working, in percent."""
        return round(100 * self.active_seconds / self.open_seconds) if self.open_seconds else 0
