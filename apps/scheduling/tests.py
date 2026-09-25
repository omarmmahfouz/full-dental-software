from datetime import datetime, time, timedelta

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import Branch, UserProfile
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
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
        self.dentist = make_dentist("dentist")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
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

    def test_walk_in_uses_the_dentists_room_shift(self):
        now = timezone.localtime()
        RoomShift.objects.create(room=self.room, date=now.date(), start_time=time(0, 0), end_time=time(23, 59),
                                 dentist=self.dentist)
        self.client.post("/schedule/walk-in/", {"patient_lookup": self.patient.file_number})
        appointment = Appointment.objects.get()
        self.assertTrue(appointment.is_walk_in)
        self.assertEqual(appointment.status, Appointment.Status.ARRIVED)
        self.assertEqual((appointment.dentist, appointment.room), (self.dentist, self.room))

    def test_booking_defaults_to_responsible_dentist_and_blocks_double_booking(self):
        when = (timezone.localtime() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
        data = {"patient_lookup": self.patient.phone_primary, "scheduled_at": when.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 60}
        self.client.post("/schedule/appointments/new/", data)
        self.assertEqual(Appointment.objects.get().dentist, self.dentist)
        data["scheduled_at"] = (when + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post("/schedule/appointments/new/", data)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_dentist_cannot_use_board(self):
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/schedule/today/").status_code, 403)
        self.assertEqual(self.client.get("/schedule/rooms/").status_code, 200)


class RoomScheduleTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist")
        self.dentist2 = make_dentist("dentist2")
        self.room1, self.room2 = Room.objects.filter(branch=self.branch)[:2]
        self.day = timezone.localdate()

    def shift(self, room, dentist, start, end):
        return RoomShift(room=room, date=self.day, start_time=time(start), end_time=time(end), dentist=dentist)

    def test_room_and_dentist_clashes_are_blocked(self):
        self.shift(self.room1, self.dentist, 9, 13).save()
        with self.assertRaises(ValidationError):
            self.shift(self.room1, self.dentist2, 12, 15).full_clean()  # same room overlaps
        with self.assertRaises(ValidationError):
            self.shift(self.room2, self.dentist, 10, 11).full_clean()  # same dentist in two rooms
        self.shift(self.room1, self.dentist2, 13, 17).full_clean()  # back-to-back is fine
        with self.assertRaises(ValidationError):
            self.shift(self.room2, self.dentist2, 14, 12).full_clean()  # end before start

    def test_copy_previous_week(self):
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        this_week = week_start(self.day)
        last_week_day = this_week - timedelta(days=7)
        RoomShift.objects.create(room=self.room1, date=last_week_day, start_time=time(9), end_time=time(13), dentist=self.dentist,
                                 day_type=RoomShift.DayType.SURGERY)
        self.client.post("/schedule/rooms/copy-week/", {"week": this_week.isoformat()})
        self.assertTrue(RoomShift.objects.filter(date=this_week, room=self.room1, dentist=self.dentist,
                                                 day_type=RoomShift.DayType.SURGERY).exists())
        # Copying twice does not create clashing duplicates.
        self.client.post("/schedule/rooms/copy-week/", {"week": this_week.isoformat()})
        self.assertEqual(RoomShift.objects.filter(date=this_week).count(), 1)

    def test_week_starts_on_saturday(self):
        self.assertEqual(week_start(self.day).weekday(), 5)


class DentistScheduleTests(TestCase):
    def test_cia_dentist_sees_only_their_own_shifts(self):
        branch = setup_clinic()
        dentist = make_dentist("dentist", kind="fulltime")
        other = make_dentist("dentist2", kind="fulltime")
        room1, room2 = Room.objects.filter(branch=branch)[:2]
        day = timezone.localdate()
        RoomShift.objects.create(room=room1, date=day, start_time=time(9), end_time=time(13), dentist=dentist)
        RoomShift.objects.create(room=room2, date=day, start_time=time(9), end_time=time(13), dentist=other)
        self.client.login(username="dentist", password=PASSWORD)
        rows = self.client.get("/schedule/rooms/").context["rows"]
        shifts = [shift for _room, cells in rows for _day, day_shifts in cells for shift in day_shifts]
        self.assertEqual([s.dentist for s in shifts], [dentist])
        head = make_dentist("head", kind="fulltime")
        head.user.groups.add(Group.objects.get(name="team_head"))
        self.client.login(username="head", password=PASSWORD)
        rows = self.client.get("/schedule/rooms/").context["rows"]
        self.assertEqual(sum(len(day_shifts) for _room, cells in rows for _day, day_shifts in cells), 2)


class WhatsAppTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        Branch.objects.filter(pk=self.branch.pk).update(phone="0223456789")
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("dentist", kind="fulltime", name="Dr. Mona")
        self.patient = make_patient(self.branch, phone="01001234567")
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.appointment = Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist,
                                                      scheduled_at=at(tomorrow, 11, 30))
        self.client.login(username="sec", password=PASSWORD)

    def test_numbers_for_whatsapp(self):
        from apps.scheduling.whatsapp import whatsapp_number

        self.assertEqual(whatsapp_number("01001234567"), "201001234567")
        self.assertEqual(whatsapp_number("+20 100 123 4567"), "201001234567")
        self.assertEqual(whatsapp_number("+966 50 123 4567"), "966501234567")
        self.assertEqual(whatsapp_number(""), "")

    def test_send_opens_whatsapp_with_the_message_and_keeps_it(self):
        from urllib.parse import unquote

        from apps.scheduling.models import SentMessage

        self.assertEqual(self.client.get(f"/schedule/whatsapp/{self.appointment.pk}/confirmation/").status_code, 405)
        response = self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/confirmation/")
        self.assertTrue(response["Location"].startswith("https://wa.me/201001234567?text="))
        text = unquote(response["Location"].split("text=", 1)[1])
        self.assertIn(self.patient.full_name, text)
        self.assertIn("Dr. Mona", text)
        self.assertIn("0223456789", text)
        self.dentist.name_ar = "د. منى"
        self.dentist.save()
        response = self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/reminder/")
        text = unquote(response["Location"].split("text=", 1)[1])
        self.assertIn("د. منى", text)  # the whole message in Arabic
        self.assertNotIn("Dr. Mona", text)
        message = SentMessage.objects.get(kind="confirmation")
        self.assertEqual((message.kind, message.sent_by, message.appointment), ("confirmation", self.secretary,
                                                                                  self.appointment))

    def test_read_only_secretary_cannot_send(self):
        from apps.scheduling.models import SentMessage

        UserProfile.objects.filter(user=self.secretary).update(read_only=True)
        self.assertEqual(self.client.get("/schedule/whatsapp/").status_code, 200)
        self.assertEqual(self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/reminder/").status_code, 403)
        self.assertFalse(SentMessage.objects.exists())

    def test_messages_to_send(self):
        page = self.client.get("/schedule/whatsapp/")
        self.assertEqual([a for a, sent in page.context["reminders"]], [self.appointment])
        self.assertEqual([a for a, sent in page.context["new_bookings"]], [self.appointment])
        self.assertEqual(self.client.get("/").context["whatsapp_to_send"], 2)
        self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/reminder/")
        page = self.client.get("/schedule/whatsapp/")
        self.assertIsNotNone(page.context["reminders"][0][1])
        self.appointment.status = Appointment.Status.NO_SHOW
        self.appointment.scheduled_at = timezone.now() - timedelta(days=1)
        self.appointment.save()
        page = self.client.get("/schedule/whatsapp/")
        self.assertEqual([a for a, sent in page.context["missed"]], [self.appointment])

    def test_editable_text_and_dentists_cannot_send(self):
        from apps.scheduling.models import MessageTemplate

        MessageTemplate.objects.filter(kind="reminder").update(text="Hello {patient}, see you {date} {unknown}")
        response = self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/reminder/")
        self.assertIn("%7Bunknown%7D", response["Location"])  # unknown words are left as they are
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/reminder/").status_code, 403)


class DayPlannerTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("dentist", kind="fulltime", name="Dr. Mona")
        self.candidate = make_dentist("cand", kind="candidate", login=False, name="Dr. Candidate")
        self.room = Room.objects.filter(branch=self.branch).first()
        self.day = timezone.localdate() + timedelta(days=1)
        RoomShift.objects.create(room=self.room, date=self.day, start_time=time(9), end_time=time(17),
                                 dentist=self.dentist)
        self.patient = make_patient(self.branch)
        for minute in (0, 30):
            Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist, room=self.room,
                                       scheduled_at=at(self.day, 9, minute), duration_minutes=30)
        self.client.login(username="sec", password=PASSWORD)

    def test_the_day_room_by_room(self):
        page = self.client.get("/schedule/day/", {"day": self.day.isoformat()})
        column = next(c for c in page.context["columns"] if c["room"] == self.room)
        self.assertEqual([b["top"] for b in column["blocks"]], [0, 44])
        free = [slot for slot in column["slots"] if slot["shift"]]
        self.assertEqual((free[0]["time"], free[-1]["time"], free[0]["dentist_id"]), ("09:00", "16:45", self.dentist.pk))
        self.assertEqual(sum(w["booked"] for w in page.context["week"]), 2)
        fragment = self.client.get("/schedule/day/", {"day": self.day.strftime("%d/%m/%Y"), "fragment": "1"})
        self.assertContains(fragment, f'data-time="10:00" data-room="{self.room.pk}" data-dentist="{self.dentist.pk}"')
        self.assertContains(fragment, "target=\"_blank\"")
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/schedule/day/").status_code, 403)

    def test_overlapping_bookings_sit_side_by_side(self):
        Appointment.objects.create(branch=self.branch, patient=make_patient(self.branch, nid="29002021234568",
                                                                            phone="01101234567"),
                                   room=self.room, scheduled_at=at(self.day, 9, 15), duration_minutes=30)
        page = self.client.get("/schedule/day/", {"day": self.day.isoformat()})
        column = next(c for c in page.context["columns"] if c["room"] == self.room)
        self.assertEqual(sorted((b["left"], b["width"]) for b in column["blocks"]), [(0, 50), (0, 50), (50, 50)])

    def test_shift_dentist_from_either_list_and_surgery_days(self):
        data = {"room": self.room.pk, "date": (self.day + timedelta(days=7)).strftime("%d/%m/%Y"),
                "day_type": "regular", "start_time": "09:00", "end_time": "13:00"}
        response = self.client.post("/schedule/rooms/shift/new/", {**data, "dentist": self.dentist.pk,
                                                                    "other_dentist": self.candidate.pk})
        self.assertIn("other_dentist", response.context["form"].errors)
        self.client.post("/schedule/rooms/shift/new/", {**data, "other_dentist": self.candidate.pk})
        shift = RoomShift.objects.get(dentist=self.candidate)
        edit = self.client.get(f"/schedule/rooms/shift/{shift.pk}/")
        self.assertEqual(edit.context["form"].initial["other_dentist"], self.candidate.pk)
        thursday = self.day + timedelta(days=(3 - self.day.weekday()) % 7)
        form = self.client.get("/schedule/rooms/shift/new/", {"date": thursday.isoformat()}).context["form"]
        self.assertEqual(form.initial["day_type"], RoomShift.DayType.SURGERY)
