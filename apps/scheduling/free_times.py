"""Finding free times: the nearest days and hours a dentist (or any dentist) is on the room
schedule with nobody booked, and whether a dentist works on a given day."""

from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .models import Appointment, RoomShift, day_bounds

STEP = 15
NOT_BUSY = (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW, Appointment.Status.LATE_NOT_SEEN)


def _minutes(value):
    return value.hour * 60 + value.minute


def _at(day, minute):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute))


def free_times(branch, duration, dentist=None, start=None, days=45, limit=8):
    """The first free time of each shift, day after day, from ``start`` (default: now)."""
    now = timezone.localtime()
    start = timezone.localtime(start) if start else now
    duration = max(int(duration or 30), 5)
    found = []
    for offset in range(days):
        day = start.date() + timedelta(days=offset)
        shifts = RoomShift.objects.filter(room__branch=branch, room__is_active=True, date=day, dentist__isnull=False)
        if dentist is not None:
            shifts = shifts.filter(dentist=dentist)
        shifts = list(shifts.select_related("room", "dentist").order_by("start_time"))
        if not shifts:
            continue
        begin, end = day_bounds(day)
        booked = list(Appointment.objects.filter(branch=branch, scheduled_at__gte=begin, scheduled_at__lt=end)
                      .exclude(status__in=NOT_BUSY))
        for shift in shifts:
            minute, last = _minutes(shift.start_time), _minutes(shift.end_time)
            if day == start.date():
                current = _minutes(start) + (-_minutes(start) % STEP)
                minute = max(minute, current)
            while minute + duration <= last:
                slot_start, slot_end = _at(day, minute), _at(day, minute + duration)
                clash = [a for a in booked if (a.room_id == shift.room_id or a.dentist_id == shift.dentist_id)
                         and a.scheduled_at < slot_end and a.scheduled_end > slot_start]
                if not clash:
                    found.append({"at": slot_start, "shift": shift})
                    break
                blocked_until = max(_minutes(timezone.localtime(a.scheduled_end)) for a in clash)
                minute = max(minute + STEP, blocked_until + (-blocked_until % STEP))
        if len(found) >= limit:
            break
    found.sort(key=lambda item: item["at"])
    return found[:limit]


def dentist_day(dentist, day):
    """The dentist's shifts on ``day`` and a sentence for the reception."""
    shifts = list(RoomShift.objects.filter(Q(dentist=dentist) | Q(second_dentist=dentist), date=day)
                  .select_related("room").order_by("start_time"))
    when = date_format(day, "l d/m/Y")
    if not shifts:
        text = _("%(dentist)s is not on the room schedule on %(day)s. You can still book: the supervisor will be "
                 "told, and you can send the dentist a WhatsApp message.") % {"dentist": dentist, "day": when}
    else:
        parts = [f"{s.room} {s.start_time:%H:%M}–{s.end_time:%H:%M}" for s in shifts]
        text = _("%(dentist)s works on %(day)s: %(where)s.") % {"dentist": dentist, "day": when,
                                                               "where": " · ".join(parts)}
    return {"working": bool(shifts), "text": text,
            "shifts": [{"room_id": s.room_id, "room": str(s.room), "from": f"{s.start_time:%H:%M}",
                        "to": f"{s.end_time:%H:%M}", "surgery": s.day_type == RoomShift.DayType.SURGERY}
                       for s in shifts]}
