from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic
from apps.scheduling.models import Appointment, Room, RoomShift
from apps.scheduling.views import week_start


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


@override_settings(CLINIC={"LATE_THRESHOLD_MINUTES": 10, "DEFAULT_APPOINTMENT_MINUTES": 60,
                           "COMPLAINT_FOLLOW_UP_DAYS": 2, "DEFAULT_BRANCH_CODE": "CIA", "CURRENCY": "EGP"})
class VisitTimingTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        self.day = timezone.localdate()

    def test_timing_figures(self):
        appointment = Appointment(branch=self.branch, patient=self.patient, scheduled_at=at(self.day, 10))
        appointment.mark_arrived(at(self.day, 10, 25))
        appointment.mark_entered_room(at(self.day, 10, 40))
        appointment.mark_left(at(self.day, 11, 30))
        self.assertEqual(appointment.late_minutes, 25)
        self.assertTrue(appointment.is_late)
        self.assertEqual(appointment.waiting_minutes, 15)
        self.assertEqual(appointment.chair_minutes, 50)
        self.assertEqual(appointment.total_minutes, 65)
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_early_and_slightly_late_are_not_late(self):
        early = Appointment(branch=self.branch, patient=self.patient, scheduled_at=at(self.day, 10))
        early.mark_arrived(at(self.day, 9, 50))
        self.assertEqual(early.late_minutes, 0)
        self.assertFalse(early.is_late)
        slightly = Appointment(branch=self.branch, patient=self.patient, scheduled_at=at(self.day, 10))
        slightly.mark_arrived(at(self.day, 10, 10))
        self.assertFalse(slightly.is_late)

    def test_walk_in_is_never_late(self):
        walk_in = Appointment(branch=self.branch, patient=self.patient, scheduled_at=at(self.day, 10), is_walk_in=True)
        walk_in.mark_arrived(at(self.day, 12))
        self.assertIsNone(walk_in.late_minutes)


class ReceptionBoardTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.intern = make_user("intern", "intern")
        self.patient = make_patient(self.branch, assigned_intern=self.intern)
        self.room = Room.objects.filter(branch=self.branch).first()
        self.client.login(username="sec", password=PASSWORD)

    def test_arrive_enter_leave_undo(self):
        appointment = Appointment.objects.create(branch=self.branch, patient=self.patient, scheduled_at=timezone.now())
        url = f"/schedule/appointments/{appointment.pk}/action/"
        self.client.post(url, {"action": "arrive"})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.ARRIVED)
        self.assertIsNotNone(appointment.arrived_at)
        self.client.post(url, {"action": "enter", "room": self.room.pk})
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.room), (Appointment.Status.IN_ROOM, self.room))
        self.client.post(url, {"action": "leave"})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)
        self.assertIsNotNone(appointment.left_at)
        self.client.post(url, {"action": "undo"})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.IN_ROOM)
        self.assertIsNone(appointment.left_at)

    def test_walk_in_uses_the_interns_room_shift(self):
        now = timezone.localtime()
        RoomShift.objects.create(room=self.room, date=now.date(), start_time=time(0, 0), end_time=time(23, 59),
                                 intern=self.intern)
        self.client.post("/schedule/walk-in/", {"patient_lookup": self.patient.file_number})
        appointment = Appointment.objects.get()
        self.assertTrue(appointment.is_walk_in)
        self.assertEqual(appointment.status, Appointment.Status.ARRIVED)
        self.assertEqual((appointment.intern, appointment.room), (self.intern, self.room))

    def test_booking_defaults_to_responsible_intern_and_blocks_double_booking(self):
        when = (timezone.localtime() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
        data = {"patient_lookup": self.patient.phone_primary, "scheduled_at": when.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 60}
        self.client.post("/schedule/appointments/new/", data)
        self.assertEqual(Appointment.objects.get().intern, self.intern)
        data["scheduled_at"] = (when + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post("/schedule/appointments/new/", data)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_intern_cannot_use_board(self):
        self.client.login(username="intern", password=PASSWORD)
        self.assertEqual(self.client.get("/schedule/today/").status_code, 403)
        self.assertEqual(self.client.get("/schedule/rooms/").status_code, 200)


class RoomScheduleTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.intern = make_user("intern", "intern")
        self.intern2 = make_user("intern2", "intern")
        self.room1, self.room2 = Room.objects.filter(branch=self.branch)[:2]
        self.day = timezone.localdate()

    def shift(self, room, intern, start, end):
        return RoomShift(room=room, date=self.day, start_time=time(start), end_time=time(end), intern=intern)

    def test_room_and_intern_clashes_are_blocked(self):
        self.shift(self.room1, self.intern, 9, 13).save()
        with self.assertRaises(ValidationError):
            self.shift(self.room1, self.intern2, 12, 15).full_clean()  # same room overlaps
        with self.assertRaises(ValidationError):
            self.shift(self.room2, self.intern, 10, 11).full_clean()  # same intern in two rooms
        self.shift(self.room1, self.intern2, 13, 17).full_clean()  # back-to-back is fine
        with self.assertRaises(ValidationError):
            self.shift(self.room2, self.intern2, 14, 12).full_clean()  # end before start

    def test_copy_previous_week(self):
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        this_week = week_start(self.day)
        last_week_day = this_week - timedelta(days=7)
        RoomShift.objects.create(room=self.room1, date=last_week_day, start_time=time(9), end_time=time(13), intern=self.intern)
        self.client.post("/schedule/rooms/copy-week/", {"week": this_week.isoformat()})
        self.assertTrue(RoomShift.objects.filter(date=this_week, room=self.room1, intern=self.intern).exists())
        # Copying twice does not create clashing duplicates.
        self.client.post("/schedule/rooms/copy-week/", {"week": this_week.isoformat()})
        self.assertEqual(RoomShift.objects.filter(date=this_week).count(), 1)

    def test_week_starts_on_saturday(self):
        self.assertEqual(week_start(self.day).weekday(), 5)
