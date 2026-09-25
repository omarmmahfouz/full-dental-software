from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel
from apps.core.utils import minutes_between


class Room(models.Model):
    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="rooms")
    name = models.CharField(_("name"), max_length=50)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["branch", "sort_order", "name"]
        verbose_name = _("room")
        verbose_name_plural = _("rooms")
        constraints = [models.UniqueConstraint(fields=["branch", "name"], name="unique_room_name_per_branch")]

    def __str__(self):
        return self.name


class RoomShift(TimeStampedModel):
    """The room schedule: which dentist works in which room, on which day and hours,
    under which supervisor, on a regular clinic day or a surgery day."""

    class DayType(models.TextChoices):
        REGULAR = "regular", _("Regular day")
        SURGERY = "surgery", _("Surgery day")

    room = models.ForeignKey(Room, verbose_name=_("room"), on_delete=models.CASCADE, related_name="shifts")
    day_type = models.CharField(_("day type"), max_length=10, choices=DayType.choices, default=DayType.REGULAR)
    date = models.DateField(_("date"), db_index=True)
    start_time = models.TimeField(_("from"))
    end_time = models.TimeField(_("to"))
    dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("dentist"), on_delete=models.PROTECT, related_name="room_shifts",
        null=True,
    )
    supervisor = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("supervisor"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="supervised_shifts",
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta:
        ordering = ["date", "start_time", "room"]
        verbose_name = _("room shift")
        verbose_name_plural = _("room schedule")

    def __str__(self):
        return f"{self.room} {self.date} {self.start_time:%H:%M}-{self.end_time:%H:%M} {self.dentist}"

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": _("The end time must be after the start time.")})
        if not (self.room_id and self.date and self.start_time and self.end_time):
            return
        overlapping = RoomShift.objects.filter(
            date=self.date, start_time__lt=self.end_time, end_time__gt=self.start_time
        ).exclude(pk=self.pk)
        clash = overlapping.filter(room_id=self.room_id).select_related("dentist").first()
        if clash:
            raise ValidationError(
                _("%(room)s is already booked for %(dentist)s from %(start)s to %(end)s.")
                % {"room": self.room, "dentist": clash.dentist, "start": f"{clash.start_time:%H:%M}",
                   "end": f"{clash.end_time:%H:%M}"}
            )
        if self.dentist_id:
            clash = overlapping.filter(dentist_id=self.dentist_id).select_related("room").first()
            if clash:
                raise ValidationError(
                    {"dentist": _("This dentist already works in %(room)s at that time.") % {"room": clash.room}}
                )


class Appointment(TimeStampedModel):
    """A booked (or walk-in) visit, with the real arrival / room-entry / leaving times."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Booked")
        CONFIRMED = "confirmed", _("Confirmed by phone")
        ARRIVED = "arrived", _("Arrived - waiting")
        IN_ROOM = "in_room", _("In the room")
        COMPLETED = "completed", _("Left")
        NO_SHOW = "no_show", _("Did not come")
        CANCELLED = "cancelled", _("Cancelled")

    WAITING_STATUSES = (Status.SCHEDULED, Status.CONFIRMED)
    CLOSED_STATUSES = (Status.COMPLETED, Status.NO_SHOW, Status.CANCELLED)

    branch = models.ForeignKey(Branch, verbose_name=_("branch"), on_delete=models.PROTECT, related_name="appointments")
    patient = models.ForeignKey(
        "patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT, related_name="appointments"
    )
    scheduled_at = models.DateTimeField(_("appointment time"), db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(_("expected duration (minutes)"), default=60)
    room = models.ForeignKey(
        Room, verbose_name=_("room"), null=True, blank=True, on_delete=models.SET_NULL, related_name="appointments"
    )
    dentist = models.ForeignKey(
        "dentists.Dentist", verbose_name=_("dentist"), null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appointments",
    )
    purpose = models.CharField(_("planned procedure"), max_length=200, blank=True)
    is_walk_in = models.BooleanField(_("walk-in (no booking)"), default=False)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    arrived_at = models.DateTimeField(_("arrived at clinic"), null=True, blank=True)
    entered_room_at = models.DateTimeField(_("entered the room"), null=True, blank=True)
    left_at = models.DateTimeField(_("left"), null=True, blank=True)
    cancel_reason = models.CharField(_("cancellation reason"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        verbose_name = _("appointment")
        verbose_name_plural = _("appointments")

    def __str__(self):
        local = timezone.localtime(self.scheduled_at)
        return f"{self.patient.full_name} - {local:%Y-%m-%d %H:%M}"

    def get_absolute_url(self):
        return reverse("scheduling:appointment_detail", args=[self.pk])

    @property
    def scheduled_end(self):
        return self.scheduled_at + timedelta(minutes=self.duration_minutes)

    # ---- timing statistics (minutes) --------------------------------------
    @property
    def late_minutes(self):
        """Minutes the patient arrived after the booked time (0 if early, None for walk-ins)."""
        if self.is_walk_in or not self.arrived_at:
            return None
        return max(minutes_between(self.scheduled_at, self.arrived_at), 0)

    @property
    def is_late(self):
        late = self.late_minutes
        return late is not None and late > settings.CLINIC["LATE_THRESHOLD_MINUTES"]

    @property
    def waiting_minutes(self):
        return minutes_between(self.arrived_at, self.entered_room_at)

    @property
    def chair_minutes(self):
        return minutes_between(self.entered_room_at, self.left_at)

    @property
    def total_minutes(self):
        return minutes_between(self.arrived_at, self.left_at)

    # ---- front-desk actions ------------------------------------------------
    def mark_arrived(self, when=None):
        self.arrived_at = when or timezone.now()
        self.status = self.Status.ARRIVED

    def mark_entered_room(self, when=None):
        when = when or timezone.now()
        if not self.arrived_at:
            self.arrived_at = when
        self.entered_room_at = when
        self.status = self.Status.IN_ROOM

    def mark_left(self, when=None):
        when = when or timezone.now()
        if not self.arrived_at:
            self.arrived_at = when
        if not self.entered_room_at:
            self.entered_room_at = when
        self.left_at = when
        self.status = self.Status.COMPLETED

    def undo_last_step(self):
        """Let the secretary fix a button pressed by mistake."""
        if self.status == self.Status.COMPLETED:
            self.left_at = None
            self.status = self.Status.IN_ROOM
        elif self.status == self.Status.IN_ROOM:
            self.entered_room_at = None
            self.status = self.Status.ARRIVED
        elif self.status == self.Status.ARRIVED:
            self.arrived_at = None
            self.status = self.Status.SCHEDULED
        elif self.status in (self.Status.NO_SHOW, self.Status.CANCELLED):
            self.status = self.Status.SCHEDULED
            self.cancel_reason = ""

    def find_shift(self):
        """The room shift that covers this appointment for its dentist, if any."""
        if not self.dentist_id:
            return None
        local = timezone.localtime(self.scheduled_at)
        return (
            RoomShift.objects.filter(
                dentist_id=self.dentist_id, date=local.date(), start_time__lte=local.time(), end_time__gt=local.time()
            )
            .select_related("room")
            .first()
        )


def day_bounds(day):
    """Aware datetimes for the start of ``day`` and of the next day (local time)."""
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return start, start + timedelta(days=1)
