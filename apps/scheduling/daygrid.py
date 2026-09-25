"""The day planner: one column per room, the day in 15-minute steps, the booked
patients as blocks and the free time as places to click and book."""

from datetime import time

from django.utils import timezone

from apps.core.models import ClinicSettings
from apps.core.widgets import time_label

from .models import Appointment, Room, RoomShift, day_bounds

SLOT = 15  # minutes per step of the grid
ROW_PX = 22  # height of one step on screen


def _minutes(value):
    return value.hour * 60 + value.minute


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _place(appointments, first):
    """Position the blocks; appointments at the same time in one room sit side by side."""
    placed, cluster, cluster_end = [], [], -1

    def close(cluster):
        lanes = max((item["lane"] for item in cluster), default=0) + 1
        for item in cluster:
            item["width"] = 100 // lanes
            item["left"] = item["lane"] * 100 // lanes

    lane_ends = []
    for appointment in sorted(appointments, key=lambda a: a.scheduled_at):
        start = _minutes(timezone.localtime(appointment.scheduled_at))
        end = start + max(appointment.duration_minutes or SLOT, SLOT)
        if start >= cluster_end:
            close(cluster)
            cluster, lane_ends = [], []
        lane = next((i for i, lane_end in enumerate(lane_ends) if lane_end <= start), None)
        if lane is None:
            lane_ends.append(end)
            lane = len(lane_ends) - 1
        else:
            lane_ends[lane] = end
        item = {"appointment": appointment, "lane": lane,
                "top": round((start - first) / SLOT * ROW_PX), "height": round((end - start) / SLOT * ROW_PX) - 2}
        cluster.append(item)
        placed.append(item)
        cluster_end = max(cluster_end, end)
    close(cluster)
    return placed


def day_grid(branch, day, dentist=None):
    options = ClinicSettings.get()
    rooms = list(Room.objects.filter(branch=branch, is_active=True))
    shifts = list(RoomShift.objects.filter(room__in=rooms, date=day).select_related("dentist", "supervisor"))
    start, end = day_bounds(day)
    appointments = (Appointment.objects.filter(branch=branch, scheduled_at__gte=start, scheduled_at__lt=end)
                    .exclude(status=Appointment.Status.CANCELLED).select_related("patient", "dentist", "room"))
    if dentist is not None:
        appointments = appointments.filter(dentist=dentist)
    appointments = list(appointments)
    used = {s.room_id for s in shifts} | {a.room_id for a in appointments}
    rooms = [room for room in rooms if not room.is_extra or room.pk in used]  # extra rooms only when opened

    first, last = _minutes(options.day_start), _minutes(options.day_end)
    for shift in shifts:
        first, last = min(first, _minutes(shift.start_time)), max(last, _minutes(shift.end_time))
    for appointment in appointments:
        begin = _minutes(timezone.localtime(appointment.scheduled_at))
        first, last = min(first, begin), max(last, begin + (appointment.duration_minutes or SLOT))
    first -= first % SLOT
    last = min(last + (-last % SLOT), 24 * 60)
    rows = max((last - first) // SLOT, 1)

    room_ids = {room.pk for room in rooms}
    columns = []
    loose = [a for a in appointments if a.room_id not in room_ids]
    for room in rooms + ([None] if loose else []):
        room_shifts = [s for s in shifts if room is not None and s.room_id == room.pk]
        slots = []
        for step in range(rows):
            minute = first + step * SLOT
            shift = next((s for s in room_shifts if _minutes(s.start_time) <= minute < _minutes(s.end_time)), None)
            slots.append({"top": step * ROW_PX, "time": _hhmm(minute), "shift": shift,
                          "dentist_id": shift.dentist_id if shift else ""})
        columns.append({
            "room": room,
            "shifts": room_shifts,
            "surgery": any(s.day_type == RoomShift.DayType.SURGERY for s in room_shifts),
            "slots": slots,
            "blocks": _place(loose if room is None else [a for a in appointments if a.room_id == room.pk], first),
        })
    marks = [{"top": (m - first) // SLOT * ROW_PX, "label": time_label(time(m // 60, m % 60)),
              "hour": m % 60 == 0}
             for m in range(first, first + rows * SLOT, 30)]
    return {"day": day, "columns": columns, "height": rows * ROW_PX, "row_px": ROW_PX, "marks": marks,
            "booked": len(appointments)}


def week_outline(branch, week_days):
    """For each day: how many patients are booked and how many free places are left in
    the staffed hours (at the usual appointment length)."""
    length = ClinicSettings.get().default_appointment_minutes or 30
    start, _end = day_bounds(week_days[0])
    _start, end = day_bounds(week_days[-1])
    booked = {}
    for appointment in (Appointment.objects.filter(branch=branch, scheduled_at__gte=start, scheduled_at__lt=end)
                        .exclude(status=Appointment.Status.CANCELLED).only("scheduled_at")):
        day = timezone.localtime(appointment.scheduled_at).date()
        booked[day] = booked.get(day, 0) + 1
    capacity, surgery, rooms_open = {}, set(), {}
    for shift in RoomShift.objects.filter(room__branch=branch, room__is_active=True, date__range=(week_days[0], week_days[-1])):
        minutes = _minutes(shift.end_time) - _minutes(shift.start_time)
        capacity[shift.date] = capacity.get(shift.date, 0) + max(minutes // length, 0)
        rooms_open.setdefault(shift.date, set()).add(shift.room_id)
        if shift.day_type == RoomShift.DayType.SURGERY:
            surgery.add(shift.date)
    return [{"day": day, "booked": booked.get(day, 0), "capacity": capacity.get(day, 0),
             "free": max(capacity.get(day, 0) - booked.get(day, 0), 0), "rooms": len(rooms_open.get(day, ())),
             "surgery": day in surgery, "percent": min(round(100 * booked.get(day, 0) / capacity[day]), 100)
             if capacity.get(day) else 0}
            for day in week_days]
