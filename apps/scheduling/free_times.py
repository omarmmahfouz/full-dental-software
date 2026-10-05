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


def free_times(branch, duration, dentist=None, start=None, days=45, limit=8, fits=None):
    """The first free time of each shift, day after day, from ``start`` (default: now): [{"at", "room", "dentist"}].
    Where the rooms are shared, the first time a room and the doctor are both free. ``fits(moment)``, when given,
    keeps only the times it accepts (e.g. the days and hours the patient prefers, ``Patient.prefers``)."""
    if branch is not None and branch.rooms_shared:
        return shared_free_times(branch, duration, dentist, start, days, limit, fits)
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
                if not clash and fits is not None and not fits(timezone.localtime(slot_start)):
                    minute += STEP
                    continue
                if not clash:
                    found.append({"at": slot_start, "shift": shift, "room": shift.room, "dentist": shift.dentist})
                    break
                blocked_until = max(_minutes(timezone.localtime(a.scheduled_end)) for a in clash)
                minute = max(minute + STEP, blocked_until + (-blocked_until % STEP))
        if len(found) >= limit:
            break
    found.sort(key=lambda item: item["at"])
    return found[:limit]


def _windows(branch, dentist, day, with_shifts):
    """The hours to look in on ``day``: the doctor's own shifts when he has any on the room schedule, else the
    opening hours of the place (none on the days it is closed)."""
    if with_shifts:
        return [(_minutes(s.start_time), _minutes(s.end_time)) for s in RoomShift.objects.filter(
            Q(dentist=dentist) | Q(second_dentist=dentist), room__branch=branch, date=day).order_by("start_time")]
    if day.weekday() in branch.closed_weekdays:
        return []
    opens, closes = branch.hours()
    return [(_minutes(opens), _minutes(closes))]


def shared_free_times(branch, duration, dentist=None, start=None, days=45, limit=8, fits=None):
    """Shared rooms: the first time of each day when a room is free and the doctor has no other patient."""
    from .models import Room

    now = timezone.localtime()
    start = timezone.localtime(start) if start else now
    duration = max(int(duration or 30), 5)
    rooms = list(Room.objects.filter(branch=branch, is_active=True).order_by("is_extra", "sort_order", "name"))
    # A doctor who keeps his days on the room schedule is offered those days only.
    with_shifts = dentist is not None and RoomShift.objects.filter(
        Q(dentist=dentist) | Q(second_dentist=dentist), room__branch=branch,
        date__range=(start.date(), start.date() + timedelta(days=days))).exists()
    found = []
    for offset in range(days):
        day = start.date() + timedelta(days=offset)
        windows = _windows(branch, dentist, day, with_shifts)
        if not windows or not rooms:
            continue
        begin, end = day_bounds(day)
        booked = list(Appointment.objects.filter(branch=branch, scheduled_at__gte=begin, scheduled_at__lt=end)
                      .exclude(status__in=NOT_BUSY))
        for first, last in windows:
            minute = first
            if day == start.date():
                minute = max(minute, _minutes(start) + (-_minutes(start) % STEP))
            placed = None
            while minute + duration <= last and placed is None:
                slot_start, slot_end = _at(day, minute), _at(day, minute + duration)
                overlapping = [a for a in booked if a.scheduled_at < slot_end and a.scheduled_end > slot_start]
                doctor_busy = dentist is not None and any(a.dentist_id == dentist.pk for a in overlapping)
                taken = {a.room_id for a in overlapping}
                room = next((r for r in rooms if r.pk not in taken), None)
                if room is not None and not doctor_busy and (fits is None or fits(timezone.localtime(slot_start))):
                    placed = {"at": slot_start, "shift": None, "room": room, "dentist": dentist}
                minute += STEP
            if placed:
                found.append(placed)
                break
        if len(found) >= limit:
            break
    return found[:limit]


def dentist_day(dentist, day, branch=None):
    """The dentist's shifts on ``day`` (at this place, when given) and a sentence for the reception."""
    if branch is not None and branch.rooms_shared:
        return shared_dentist_day(dentist, day, branch)
    shifts = RoomShift.objects.filter(Q(dentist=dentist) | Q(second_dentist=dentist), date=day)
    if branch is not None:
        shifts = shifts.filter(room__branch=branch)
    shifts = list(shifts.select_related("room").order_by("start_time"))
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


def shared_dentist_day(dentist, day, branch):
    """Shared rooms: no room schedule is needed; the reception sees the doctor's patients of the day."""
    begin, end = day_bounds(day)
    booked = list(Appointment.objects.filter(branch=branch, dentist=dentist, scheduled_at__gte=begin,
                                             scheduled_at__lt=end).exclude(status__in=NOT_BUSY)
                  .select_related("room").order_by("scheduled_at"))
    when = date_format(day, "l d/m/Y")
    if booked:
        parts = [f"{timezone.localtime(a.scheduled_at):%H:%M}–{timezone.localtime(a.scheduled_end):%H:%M}"
                 f"{f' ({a.room})' if a.room_id else ''}" for a in booked]
        text = _("Rooms are shared here: a free room is chosen by itself. %(dentist)s already has on %(day)s: "
                 "%(times)s.") % {"dentist": dentist, "day": when, "times": " · ".join(parts)}
    else:
        text = _("Rooms are shared here: a free room is chosen by itself. %(dentist)s has no patient yet on "
                 "%(day)s.") % {"dentist": dentist, "day": when}
    if day.weekday() in branch.closed_weekdays:
        text += " " + _("The place is closed on this day.")
    return {"working": day.weekday() not in branch.closed_weekdays, "text": text, "shifts": []}


def day_slots(dentist, day, branch, duration=30, exclude=None):
    """The times of the doctor's shift on ``day`` in steps of 15 minutes (round 15): [{"time", "label", "busy",
    "room", "who"}]. A time is busy when the doctor already has a patient then (or, where the rooms are shared, when
    no room is free); the booking form shows them grey and they cannot be pressed. Without a shift that day, the
    place's opening hours are given with ``outside`` true."""
    from django.utils.formats import time_format

    from .models import Room

    duration = max(int(duration or 30), 5)
    shifts = list(RoomShift.objects.filter(Q(dentist=dentist) | Q(second_dentist=dentist), date=day,
                                           room__branch=branch).select_related("room").order_by("start_time"))
    outside = not shifts
    if shifts:
        windows = [(_minutes(s.start_time), _minutes(s.end_time), s.room_id) for s in shifts]
    elif day.weekday() in branch.closed_weekdays:
        return {"slots": [], "outside": True}
    else:
        opens, closes = branch.hours()
        windows = [(_minutes(opens), _minutes(closes), None)]
    begin, end = day_bounds(day)
    booked = list(Appointment.objects.filter(branch=branch, scheduled_at__gte=begin, scheduled_at__lt=end)
                  .exclude(status__in=NOT_BUSY).exclude(pk=exclude).select_related("patient"))
    rooms = list(Room.objects.filter(branch=branch, is_active=True)) if branch.rooms_shared else []
    now = timezone.localtime()
    slots = []
    for first, last, room_id in windows:
        minute = first
        while minute + min(duration, STEP) <= last:
            slot_start, slot_end = _at(day, minute), _at(day, minute + duration)
            overlapping = [a for a in booked if a.scheduled_at < slot_end and a.scheduled_end > slot_start]
            mine = [a for a in overlapping if dentist.pk in (a.dentist_id, a.second_dentist_id)]
            busy, who = bool(mine), mine[0].patient.full_name if mine else ""
            if not busy and branch.rooms_shared and rooms:
                taken = {a.room_id for a in overlapping}
                if all(r.pk in taken for r in rooms):
                    busy, who = True, _("no free room")
            elif not busy and room_id:
                other = next((a for a in overlapping if a.room_id == room_id), None)
                if other is not None:
                    busy, who = True, other.patient.full_name
            local = timezone.localtime(slot_start)
            slots.append({"time": f"{local:%H:%M}", "label": time_format(local.time(), "g:i A"), "busy": busy,
                          "past": slot_start < now, "too_long": minute + duration > last, "room": room_id or "",
                          "who": who})
            minute += STEP
    return {"slots": slots, "outside": outside}
