from datetime import datetime, time, timedelta

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone, translation

from apps.core.models import Branch, UserProfile
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.clinical.models import TreatmentStepType
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

    def test_walk_in_with_a_booked_appointment_and_follow_up_after_leaving(self):
        later = Appointment.objects.create(branch=self.branch, patient=self.patient,
                                           scheduled_at=timezone.now() + timedelta(days=3))
        response = self.client.post("/schedule/walk-in/", {"patient_lookup": self.patient.file_number})
        walk_in = Appointment.objects.get(is_walk_in=True)
        self.assertRedirects(response, f"/schedule/today/?check={walk_in.pk}", fetch_redirect_response=False)
        page = self.client.get(f"/schedule/today/?check={walk_in.pk}")
        self.assertEqual(page.context["checked"].others, [later])  # the secretary is asked: cancel or move it?
        self.client.post(f"/schedule/appointments/{later.pk}/action/", {"action": "cancel", "reason": "walk-in"})
        # the walk-in leaves with no other appointment: the reception is asked to book the next visit
        url = f"/schedule/appointments/{walk_in.pk}/action/"
        self.client.post(url, {"action": "enter", "room": self.room.pk})
        response = self.client.post(url, {"action": "leave"})
        self.assertRedirects(response, f"/schedule/today/?left={walk_in.pk}", fetch_redirect_response=False)
        page = self.client.get(f"/schedule/today/?left={walk_in.pk}")
        self.assertEqual(page.context["just_left"]["appointment"], walk_in)
        self.assertIn(f"patient={self.patient.pk}", page.context["just_left"]["book_url"])
        self.client.post(url, {"action": "no_follow_up"})
        self.assertEqual(self.client.get("/schedule/today/").context["left_rows"], [])

    def test_late_patient_not_seen_and_waiting_from_the_appointment_time(self):
        start = timezone.now().replace(second=0, microsecond=0) - timedelta(minutes=40)
        late = Appointment.objects.create(branch=self.branch, patient=self.patient, scheduled_at=start,
                                          dentist=self.dentist)
        response = self.client.post(f"/schedule/appointments/{late.pk}/action/", {"action": "late"})
        late.refresh_from_db()
        self.assertEqual(late.status, Appointment.Status.LATE_NOT_SEEN)
        self.assertTrue(response["Location"].startswith("/schedule/appointments/new/?patient="))
        early = Appointment(branch=self.branch, patient=self.patient, scheduled_at=start)
        early.mark_arrived(start - timedelta(minutes=20))  # came 20 minutes early
        early.mark_entered_room(start + timedelta(minutes=5))
        self.assertEqual(early.waiting_minutes, 5)

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

    def test_mark_several_messages_as_sent(self):
        from apps.scheduling.models import SentMessage

        self.client.post("/schedule/whatsapp/mark/reminder/", {"appointment": [self.appointment.pk]})
        sent = SentMessage.objects.get()
        self.assertEqual((sent.kind, sent.appointment, sent.sent_by), ("reminder", self.appointment, self.secretary))
        rows = self.client.get("/schedule/whatsapp/").context["reminders"]
        self.assertEqual(rows[0][1], sent)  # ticked on the list

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


class RescheduleTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.dentist = make_dentist("dentist", kind="fulltime", name="Dr. Mona")
        self.patient = make_patient(self.branch)
        self.day = timezone.localdate() + timedelta(days=1)
        self.appointment = Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist,
                                                      scheduled_at=at(self.day, 10), duration_minutes=30)

    def test_move_tells_the_dentist_and_offers_whatsapp(self):
        from apps.core.models import Notification

        self.client.login(username="sec", password=PASSWORD)
        later = self.day + timedelta(days=2)
        response = self.client.post(f"/schedule/appointments/{self.appointment.pk}/move/", {
            "scheduled_at_0": later.strftime("%d/%m/%Y"), "scheduled_at_1": "12:30", "duration_minutes": "30",
            "dentist": self.dentist.pk, "reason": "the patient asked"})
        self.assertRedirects(response, self.appointment.get_absolute_url(), fetch_redirect_response=False)
        self.appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(self.appointment.scheduled_at).date(), later)
        self.assertEqual(timezone.localtime(self.appointment.rescheduled_from).hour, 10)
        self.assertTrue(Notification.objects.filter(recipient=self.dentist.user).exists())
        self.assertEqual([a for a, _sent in self.client.get("/schedule/whatsapp/").context["moved"]], [self.appointment])
        response = self.client.post(f"/schedule/whatsapp/{self.appointment.pk}/rescheduled/")
        self.assertIn("wa.me", response["Location"])
        # The dentist sees his week and the change on his home page.
        self.client.login(username="dentist", password=PASSWORD)
        home = self.client.get("/")
        self.assertEqual(sum(len(d["appointments"]) for d in home.context["my_week"]), 1)
        self.assertEqual(len(home.context["my_updates"]), 1)

    def test_a_reason_is_needed_and_cancellations_are_told(self):
        from apps.core.models import Notification

        self.client.login(username="sec", password=PASSWORD)
        response = self.client.post(f"/schedule/appointments/{self.appointment.pk}/move/", {
            "scheduled_at_0": self.day.strftime("%d/%m/%Y"), "scheduled_at_1": "11:00", "duration_minutes": "30"})
        self.assertIn("reason", response.context["form"].errors)
        self.client.post(f"/schedule/appointments/{self.appointment.pk}/action/", {"action": "cancel"})
        self.assertEqual(Notification.objects.filter(recipient=self.dentist.user).count(), 1)


class DentistPatientListTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.head = make_user("head", "head_cia")
        self.secretary = make_user("sec", "secretary")
        self.main = make_patient(self.branch, name="Main Patient")
        self.backup = make_patient(self.branch, name="Backup Patient", nid="29001011234568", phone="01001234568")
        self.room = Room.objects.filter(branch=self.branch).first()

    def add(self, patient, kind, priority, minutes=60):
        from apps.clinical.models import TreatmentStepType

        step = TreatmentStepType.objects.get(name_en="Implant placement")
        return self.client.post("/schedule/my-patient-list/", {
            "patient_lookup": patient.file_number, "step_type": step.pk, "teeth": "46 36", "minutes": minutes,
            "kind": kind, "priority": priority, "wanted_from": timezone.localdate().strftime("%d/%m/%Y"),
        })

    def test_dentist_list_is_approved_then_booked_by_the_reception(self):
        from apps.core.models import Notification
        from apps.scheduling.models import PatientRequest

        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.add(self.main, "main", 1).status_code, 302)
        self.add(self.backup, "backup", 1, minutes=45)
        first, second = PatientRequest.objects.order_by("pk")
        self.assertEqual((first.teeth, first.status), ("46, 36", "proposed"))
        self.assertTrue(Notification.objects.filter(recipient=self.head, url="/schedule/patient-lists/approve/").exists())
        self.client.login(username="sec", password=PASSWORD)  # the reception sees nothing before approval
        self.assertEqual(len(list(self.client.get("/schedule/patient-lists/").context["groups"])), 0)
        self.assertEqual(self.client.get("/schedule/patient-lists/approve/").status_code, 403)

        self.client.login(username="head", password=PASSWORD)
        self.client.post("/schedule/patient-lists/approve/", {
            "action": "approve", "item": [first.pk, second.pk], f"minutes_{first.pk}": 90, f"note_{first.pk}": "OK",
        })
        first.refresh_from_db()
        self.assertEqual((first.status, first.approved_minutes, first.decided_by), ("approved", 90, self.head))
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, url="/schedule/patient-lists/").exists())

        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/schedule/patient-lists/")
        dentist, group = list(page.context["groups"])[0]
        self.assertEqual(([i.pk for i in group["main"]], [i.pk for i in group["backup"]]), ([first.pk], [second.pk]))
        self.assertIn("duration=90", group["main"][0].book_url)
        # the main patient cannot come: the reception is told to call the backup list
        self.client.post(f"/schedule/patient-lists/{first.pk}/cannot-come/", {"note": "travelling"})
        dentist, group = list(self.client.get("/schedule/patient-lists/").context["groups"])[0]
        self.assertTrue(group["call_backup"])
        self.assertTrue(Notification.objects.filter(recipient=self.dentist.user, level="warning").exists())
        # booking the backup patient from the list links the appointment
        start = timezone.localtime().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
        RoomShift.objects.create(room=self.room, date=start.date(), start_time=time(9), end_time=time(17),
                                 dentist=self.dentist)
        response = self.client.post(
            f"/schedule/appointments/new/?patient={self.backup.pk}&dentist={self.dentist.pk}&duration=45&request={second.pk}",
            {"patient_lookup": self.backup.file_number, "scheduled_at_0": start.strftime("%d/%m/%Y"),
             "scheduled_at_1": "11:00", "duration_minutes": 45, "dentist": self.dentist.pk, "room": self.room.pk,
             "purpose": "Implant placement 46, 36"})
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        second.refresh_from_db()
        self.assertEqual(second.status, "booked")
        self.assertEqual(second.appointment.patient, self.backup)

    def test_only_dentists_have_a_list_and_can_remove_their_own(self):
        from apps.scheduling.models import PatientRequest

        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/schedule/my-patient-list/").status_code, 403)
        self.client.login(username="dentist", password=PASSWORD)
        self.add(self.main, "main", 2)
        item = PatientRequest.objects.get()
        other = make_dentist("dentist2", kind="fulltime")
        self.client.login(username="dentist2", password=PASSWORD)
        self.assertEqual(self.client.post(f"/schedule/my-patient-list/{item.pk}/remove/").status_code, 404)
        self.client.login(username="dentist", password=PASSWORD)
        self.client.post(f"/schedule/my-patient-list/{item.pk}/remove/")
        item.refresh_from_db()
        self.assertEqual(item.status, "cancelled")
        self.assertIsNotNone(other)


class SmartBookingTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.head = make_user("head", "head_cia")
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.dentist.phone = "01001112223"
        self.dentist.save()
        self.patient = make_patient(self.branch)
        self.room = Room.objects.filter(branch=self.branch).first()
        self.day = timezone.localdate() + timedelta(days=2)
        RoomShift.objects.create(room=self.room, date=self.day, start_time=time(9), end_time=time(12),
                                 dentist=self.dentist)
        self.client.login(username="sec", password=PASSWORD)

    def test_nearest_free_times_skip_booked_places(self):
        taken = timezone.make_aware(datetime.combine(self.day, time(9)))
        Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist, room=self.room,
                                   scheduled_at=taken, duration_minutes=60)
        rows = self.client.get(f"/schedule/free-times/?dentist={self.dentist.pk}&duration=30").json()["results"]
        self.assertEqual((rows[0]["date"], rows[0]["time"], rows[0]["room"]),
                         (self.day.strftime("%d/%m/%Y"), "10:00", self.room.pk))
        self.assertTrue(self.client.get("/schedule/free-times/?duration=30").json()["results"])  # any dentist

    def test_dentist_day_and_booking_outside_his_schedule(self):
        from apps.core.models import Notification

        info = self.client.get(f"/schedule/dentist-day/?dentist={self.dentist.pk}&day={self.day:%d/%m/%Y}").json()
        self.assertEqual((info["working"], info["shifts"][0]["room_id"]), (True, self.room.pk))
        other_day = self.day + timedelta(days=1)
        info = self.client.get(f"/schedule/dentist-day/?dentist={self.dentist.pk}&day={other_day:%d/%m/%Y}").json()
        self.assertFalse(info["working"])
        step = TreatmentStepType.objects.get(name_en="Scaling")
        response = self.client.post("/schedule/appointments/new/", {
            "patient_lookup": self.patient.file_number, "scheduled_at_0": other_day.strftime("%d/%m/%Y"),
            "scheduled_at_1": "10:00", "duration_minutes": 30, "dentist": self.dentist.pk, "procedure": step.pk})
        appointment = Appointment.objects.get()
        self.assertRedirects(response, appointment.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(Notification.objects.filter(recipient=self.head, url=appointment.get_absolute_url()).exists())
        page = self.client.get(appointment.get_absolute_url())
        self.assertTrue(page.context["off_schedule"])
        self.assertIn("wa.me/201001112223", page.context["dentist_whatsapp"])
        with translation.override("en"):
            self.assertEqual(str(Appointment.objects.get().what), "Scaling")
        with translation.override("ar"):
            self.assertEqual(Appointment.objects.get().what, step.name_ar)  # the reception reads it in Arabic


class WaitingListTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch)
        self.waiting_patient = make_patient(self.branch, name="Waiting", nid="29001011234568", phone="01001234568")
        self.client.login(username="sec", password=PASSWORD)
        self.day = timezone.localdate() + timedelta(days=1)

    def test_a_cancelled_place_tells_the_reception_who_is_waiting(self):
        from apps.core.models import Notification
        from apps.scheduling.models import WaitingEntry

        self.client.post("/schedule/waiting/", {"patient_lookup": self.waiting_patient.file_number,
                                                "minutes": 10, "wanted_from": self.day.strftime("%d/%m/%Y"),
                                                "notes": "can come within 30 minutes"})
        entry = WaitingEntry.objects.get()
        booked = Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist,
                                            scheduled_at=at(self.day, 11))
        self.client.post(f"/schedule/appointments/{booked.pk}/action/", {"action": "cancel"})
        note = Notification.objects.get(recipient=self.secretary, level="warning")
        self.assertIn(f"day={self.day:%Y-%m-%d}", note.url)
        rows = self.client.get(note.url).context["rows"]
        self.assertEqual([r["entry"] for r in rows], [entry])
        # booking from the list takes the patient off it; a 10-minute visit can be squeezed in
        response = self.client.post(f"{rows[0]['book_url']}", {
            "patient_lookup": self.waiting_patient.file_number, "scheduled_at_0": self.day.strftime("%d/%m/%Y"),
            "scheduled_at_1": "11:00", "duration_minutes": 10, "dentist": self.dentist.pk})
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.appointment.duration_minutes), ("booked", 10))


class VisitFlowTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.head = make_user("head", "head_cia")
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.appointment = Appointment.objects.create(branch=self.branch, patient=self.patient, dentist=self.dentist,
                                                      scheduled_at=timezone.now())

    def test_the_dentist_is_told_when_the_patient_arrives(self):
        self.client.login(username="dentist", password=PASSWORD)
        since = self.client.get("/notifications/poll/").json()["last"]
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/schedule/appointments/{self.appointment.pk}/action/", {"action": "arrive"})
        self.client.login(username="dentist", password=PASSWORD)
        data = self.client.get(f"/notifications/poll/?since={since}").json()
        self.assertEqual(len(data["new"]), 1)
        self.assertIn(self.patient.full_name, data["new"][0]["title"])
        page = self.client.get(f"/schedule/visit/{self.appointment.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["has_notes"])
        self.client.login(username="sec", password=PASSWORD)  # the visit page is for the clinical team
        self.assertEqual(self.client.get(f"/schedule/visit/{self.appointment.pk}/").status_code, 403)

    def test_visits_without_notes_remind_the_dentist_then_the_supervisor(self):
        from apps.clinical.models import TreatmentStep
        from apps.clinical.visit_notes import send_notes_alerts, visits_without_notes
        from apps.core.models import Notification

        self.appointment.mark_left(timezone.now() - timedelta(hours=2))
        self.appointment.save()
        self.assertEqual(visits_without_notes(self.dentist), [self.appointment])
        self.assertEqual(send_notes_alerts(), 1)  # the dentist after one hour
        self.assertTrue(Notification.objects.filter(recipient=self.dentist.user, level="warning").exists())
        self.assertEqual(send_notes_alerts(timezone.now() + timedelta(days=1)), 1)  # the supervisors after a day
        self.assertTrue(Notification.objects.filter(recipient=self.head, level="danger").exists())
        self.assertEqual(send_notes_alerts(timezone.now() + timedelta(days=2)), 0)  # once only
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["missing_notes"], 1)
        TreatmentStep.objects.create(patient=self.patient, appointment=self.appointment, operator=self.dentist,
                                     step_type=TreatmentStepType.objects.get(name_en="Scaling"))
        self.assertEqual(visits_without_notes(self.dentist), [])
