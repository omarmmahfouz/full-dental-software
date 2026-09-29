"""Shared rooms (El Khadem): any doctor works in any free room. A booking takes a free room by itself, a room holds
one doctor's patients at a time, and an appointment moves to another room (or swaps rooms with the patient there)
in one click."""

from datetime import timedelta

from django.db import transaction
from django.utils.translation import gettext as _

from .models import Appointment, Room

NOT_BUSY = (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW, Appointment.Status.LATE_NOT_SEEN)


def shared(branch):
    return branch is not None and branch.rooms_shared


def busy_between(branch, start, end, exclude_pk=None):
    """The appointments of the place that take a chair between ``start`` and ``end``."""
    rows = (Appointment.objects.filter(branch=branch, scheduled_at__lt=end, scheduled_at__gt=start - timedelta(hours=8))
            .exclude(status__in=NOT_BUSY).select_related("patient", "dentist", "room"))
    if exclude_pk:
        rows = rows.exclude(pk=exclude_pk)
    return [a for a in rows if a.scheduled_end > start]


def room_clash(room, start, end, dentist_id=None, exclude_pk=None):
    """Another doctor's patient in ``room`` at that time (the same doctor may see two patients in his room)."""
    for other in busy_between(room.branch, start, end, exclude_pk):
        if other.room_id == room.pk and (dentist_id is None or other.dentist_id != dentist_id):
            return other
    return None


def doctor_elsewhere(branch, dentist_id, start, end, exclude_pk=None):
    """The doctor's other patient at the same time (he may run two chairs: only a warning)."""
    if not dentist_id:
        return None
    return next((a for a in busy_between(branch, start, end, exclude_pk) if a.dentist_id == dentist_id), None)


def free_room(branch, start, end, dentist_id=None, exclude_pk=None):
    """A room free at that time: the doctor's own room of the moment first, then the regular rooms in order, then the
    extra rooms. None when every room is taken."""
    busy = busy_between(branch, start, end, exclude_pk)
    taken = {a.room_id for a in busy if a.dentist_id != dentist_id or dentist_id is None}
    own = [a.room for a in busy if dentist_id and a.dentist_id == dentist_id and a.room_id]
    rooms = list(Room.objects.filter(branch=branch, is_active=True).order_by("is_extra", "sort_order", "name"))
    for room in own + rooms:
        if room.pk not in taken:
            return room
    return None


def room_choices(appointment, rooms, day_appointments):
    """For the "change room" pop-up of one appointment: every other room, free or with the patient in it."""
    choices = []
    for room in rooms:
        if room.pk == appointment.room_id:
            continue
        clash = [o for o in day_appointments if o.pk != appointment.pk and o.room_id == room.pk
                 and o.status not in NOT_BUSY and o.scheduled_at < appointment.scheduled_end
                 and o.scheduled_end > appointment.scheduled_at]
        choices.append({"room": room, "clash": clash[0] if clash else None,
                        "swap": len(clash) == 1 and appointment.room_id is not None})
    return choices


@transaction.atomic
def change_room(appointment, room, swap=False):
    """Move the appointment to ``room``. With ``swap`` the patient in that room at that time takes this appointment's
    room. Returns (done, message)."""
    start, end = appointment.scheduled_at, appointment.scheduled_end
    clashes = [a for a in busy_between(appointment.branch, start, end, appointment.pk)
               if a.room_id == room.pk and (a.dentist_id != appointment.dentist_id or a.dentist_id is None)]
    other = clashes[0] if clashes else None
    if other is not None:
        if not swap or len(clashes) > 1 or appointment.room_id is None:
            return False, _("%(room)s is taken at this time by %(patient)s (%(dentist)s).") % {
                "room": room, "patient": other.patient.full_name, "dentist": other.dentist or "—"}
        old_room = appointment.room
        back = [a for a in busy_between(appointment.branch, other.scheduled_at, other.scheduled_end, other.pk)
                if a.room_id == old_room.pk and a.pk != appointment.pk]
        if back:
            return False, _("The rooms cannot be swapped: %(room)s is taken then too.") % {"room": old_room}
        other.room = old_room
        other.save(update_fields=["room", "updated_at"])
        appointment.room = room
        appointment.save(update_fields=["room", "updated_at"])
        return True, _("Rooms swapped: %(patient)s in %(room)s, %(other)s in %(old)s.") % {
            "patient": appointment.patient.full_name, "room": room, "other": other.patient.full_name, "old": old_room}
    appointment.room = room
    appointment.save(update_fields=["room", "updated_at"])
    return True, _("%(patient)s moved to %(room)s.") % {"patient": appointment.patient.full_name, "room": room}
