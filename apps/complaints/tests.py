from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.complaints.models import Complaint
from apps.core.models import Notification
from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic


class ComplaintTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.supervisor = make_user("sup", "supervisor")
        self.owner = make_user("owner", "owner")
        self.dentist = make_user("dentist", "dentist")
        self.patient = make_patient(self.branch)

    def test_new_complaint_notifies_supervisors_and_owner(self):
        self.client.login(username="sec", password=PASSWORD)
        self.client.post("/complaints/new/", {
            "patient_lookup": self.patient.file_number, "category": "waiting", "severity": "high",
            "description": "waited 2 hours",
        })
        complaint = Complaint.objects.get()
        self.assertTrue(complaint.number.startswith("CMP-"))
        self.assertIsNotNone(complaint.follow_up_due)
        for user in (self.supervisor, self.owner):
            note = Notification.objects.get(recipient=user)
            self.assertIn(complaint.number, note.title)
            self.assertEqual(note.level, Notification.Level.DANGER)
        self.assertFalse(Notification.objects.filter(recipient__in=[self.secretary, self.dentist]).exists())

    def test_follow_up_until_resolved(self):
        complaint = Complaint.objects.create(branch=self.branch, patient=self.patient, category="pain",
                                             description="pain", created_by=self.secretary)
        self.client.login(username="sup", password=PASSWORD)
        response = self.client.post(f"/complaints/{complaint.pk}/follow-up/", {
            "action": "called", "new_status": "in_progress", "note": "called patient",
        })
        self.assertIn("next_follow_up", response.context["form"].errors)  # open → needs a next date
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.client.post(f"/complaints/{complaint.pk}/follow-up/", {
            "action": "called", "new_status": "in_progress", "note": "called patient", "next_follow_up": tomorrow,
        })
        complaint.refresh_from_db()
        self.assertEqual((complaint.status, complaint.assigned_to), ("in_progress", self.supervisor))
        self.assertTrue(Notification.objects.filter(recipient=self.secretary).exists())
        self.client.post(f"/complaints/{complaint.pk}/follow-up/", {
            "action": "retreat", "new_status": "resolved", "note": "re-done, patient happy",
        })
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "resolved")
        self.assertEqual(complaint.resolved_by, self.supervisor)
        self.assertEqual(complaint.resolution, "re-done, patient happy")

    def test_overdue_reminders(self):
        Complaint.objects.create(branch=self.branch, patient=self.patient, category="pain", description="x",
                                 follow_up_due=timezone.localdate() - timedelta(days=1))
        call_command("send_reminders", stdout=open("/dev/null", "w"))
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor, level="danger").exists())

    def test_dentists_read_complaints_but_do_not_record_them(self):
        from apps.dentists.models import Dentist

        dentist = Dentist.objects.create(user=self.dentist, full_name="Dr Test", kind="fulltime")
        complaint = Complaint.objects.create(branch=self.branch, patient=self.patient, category="pain", description="x",
                                             concerned_dentist=dentist)
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/complaints/").status_code, 200)
        self.assertEqual(self.client.get(f"/complaints/{complaint.pk}/").status_code, 200)
        self.assertEqual(self.client.get("/complaints/new/").status_code, 403)
        self.assertEqual(self.client.post(f"/complaints/{complaint.pk}/follow-up/", {"action": "note"}).status_code, 403)


class DentistAnswerTests(TestCase):
    def test_the_dentist_answers_and_is_alerted_when_late(self):
        from apps.complaints.alerts import send_answer_alerts
        from apps.core.testing import make_dentist

        branch = setup_clinic()
        secretary = make_user("sec", "secretary")
        head = make_user("head", "head_cia")
        dentist = make_dentist("dentist", kind="fulltime")
        patient = make_patient(branch)
        self.client.login(username="sec", password=PASSWORD)
        self.client.post("/complaints/new/", {"patient_lookup": patient.file_number, "category": "pain",
                                             "severity": "medium", "description": "Pain after the filling",
                                             "concerned_dentist": dentist.pk})
        complaint = Complaint.objects.get()
        self.assertTrue(Notification.objects.filter(recipient=dentist.user, url=complaint.get_absolute_url()).exists())
        # No answer in time: the dentist and the head of CIA are alerted once.
        later = timezone.localdate() + timedelta(days=10)
        self.assertEqual(send_answer_alerts(later), 1)
        self.assertEqual(send_answer_alerts(later), 0)
        self.assertTrue(Notification.objects.filter(recipient=head, level="danger").exists())
        # The dentist writes his answer and the plan; the reception is told.
        self.client.login(username="dentist", password=PASSWORD)
        self.assertIsNotNone(self.client.get(complaint.get_absolute_url()).context["answer_form"])
        self.client.post(f"/complaints/{complaint.pk}/answer/", {"note": "Will replace the filling on Monday"})
        complaint.refresh_from_db()
        self.assertEqual((complaint.status, complaint.waiting_for_dentist), ("in_progress", False))
        self.assertTrue(Notification.objects.filter(recipient=secretary, title__contains=complaint.number).exists())
        make_dentist("other", kind="fulltime")  # not his complaint
        self.client.login(username="other", password=PASSWORD)
        self.assertEqual(self.client.post(f"/complaints/{complaint.pk}/answer/", {"note": "x"}).status_code, 403)


class OwnComplaintsTests(TestCase):
    def setUp(self):
        from apps.core.testing import make_dentist

        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.head = make_user("head", "head_cia")
        self.mine = make_dentist("dentist", kind="fulltime")
        self.other = make_dentist("other", kind="fulltime")
        patient = make_patient(self.branch)
        self.about_me = Complaint.objects.create(branch=self.branch, patient=patient, category="pain",
                                                 description="pain", concerned_dentist=self.mine,
                                                 created_by=self.secretary)
        self.about_other = Complaint.objects.create(branch=self.branch, patient=patient, category="pain",
                                                    description="pain", concerned_dentist=self.other)
        self.no_dentist = Complaint.objects.create(branch=self.branch, patient=patient, category="waiting",
                                                   description="waited")

    def test_each_dentist_sees_only_his_complaints_the_head_sees_all(self):
        self.client.login(username="dentist", password=PASSWORD)
        listed = list(self.client.get("/complaints/?status=").context["page_obj"])
        self.assertEqual(listed, [self.about_me])
        self.assertEqual(self.client.get(self.about_me.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.about_other.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(self.no_dentist.get_absolute_url()).status_code, 404)
        patient_page = self.client.get(self.about_me.patient.get_absolute_url())
        self.assertEqual(list(patient_page.context["complaints"]), [self.about_me])
        for user in ("head", "sec"):
            self.client.login(username=user, password=PASSWORD)
            self.assertEqual(len(self.client.get("/complaints/?status=").context["page_obj"]), 3)

    def test_changing_the_dentist_tells_the_new_one(self):
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/complaints/{self.no_dentist.pk}/edit/", {
            "patient_lookup": self.no_dentist.patient.file_number, "category": "waiting", "severity": "medium",
            "description": "waited", "concerned_dentist": self.other.pk,
            "follow_up_due": timezone.localdate().strftime("%d/%m/%Y"),
        })
        self.assertTrue(Notification.objects.filter(recipient=self.other.user,
                                                    url=self.no_dentist.get_absolute_url()).exists())

    def test_the_secretary_writes_what_she_did_and_the_situation(self):
        self.client.login(username="sec", password=PASSWORD)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.client.post(f"/complaints/{self.about_me.pk}/follow-up/", {
            "action": "called", "new_status": "in_progress", "note": "Called her, she will come Sunday",
            "next_follow_up": tomorrow, "current_situation": "Waiting for the Sunday visit",
        })
        self.about_me.refresh_from_db()
        self.assertEqual(self.about_me.current_situation, "Waiting for the Sunday visit")
        self.assertEqual(self.about_me.situation_updated_by, self.secretary)
        self.client.post(f"/complaints/{self.about_me.pk}/situation/", {"current_situation": "Came, filling redone"})
        self.about_me.refresh_from_db()
        self.assertEqual(self.about_me.current_situation, "Came, filling redone")
        follow_up = self.about_me.follow_ups.get()
        self.client.post(f"/complaints/{self.about_me.pk}/follow-up/{follow_up.pk}/edit/", {
            "action": "called", "note": "Called her twice, she will come Sunday", "next_follow_up": tomorrow,
        })
        follow_up.refresh_from_db()
        self.assertEqual(follow_up.note, "Called her twice, she will come Sunday")
        self.assertIsNotNone(follow_up.edited_at)
        # Someone else's follow-up cannot be corrected by a dentist.
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get(f"/complaints/{self.about_me.pk}/follow-up/{follow_up.pk}/edit/").status_code, 403)
        self.assertEqual(self.client.post(f"/complaints/{self.about_me.pk}/situation/", {"current_situation": "x"}).status_code, 403)
