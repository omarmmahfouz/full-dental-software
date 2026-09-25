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
        self.intern = make_user("intern", "intern")
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
        self.assertFalse(Notification.objects.filter(recipient__in=[self.secretary, self.intern]).exists())

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

    def test_interns_cannot_open_complaints(self):
        self.client.login(username="intern", password=PASSWORD)
        self.assertEqual(self.client.get("/complaints/").status_code, 403)
