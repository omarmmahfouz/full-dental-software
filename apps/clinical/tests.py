from django.test import TestCase

from apps.clinical.models import Lab, LabRequest, LabRequestEvent, LabWorkType, TreatmentStep, TreatmentStepType
from apps.core.models import Notification
from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic


class LabWorkflowTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.intern = make_user("intern", "intern")
        self.supervisor = make_user("sup", "supervisor")
        self.secretary = make_user("sec", "secretary")
        self.patient = make_patient(self.branch, assigned_intern=self.intern)
        self.lab = Lab.objects.first()
        self.work = LabWorkType.objects.first()

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def action(self, lab_request, action, **extra):
        return self.client.post(f"/clinical/lab/{lab_request.pk}/action/", {"action": action, **extra})

    def test_full_journey_with_reviews_and_notifications(self):
        self.login("intern")
        self.client.post("/clinical/lab/new/", {
            "patient_lookup": self.patient.file_number, "lab": self.lab.pk, "work_type": self.work.pk,
            "teeth": "36", "units": 1, "submit_for_review": "1",
        })
        lab_request = LabRequest.objects.get()
        self.assertEqual(lab_request.requested_by, self.intern)
        self.assertEqual(lab_request.status, LabRequest.Status.PENDING_REVIEW)
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor).exists())

        # The intern cannot approve his own request, the secretary cannot send before review.
        self.assertEqual(self.action(lab_request, "approve").status_code, 403)
        self.login("sec")
        self.action(lab_request, "send", checked="on")
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.PENDING_REVIEW)

        self.login("sup")
        self.action(lab_request, "approve")
        lab_request.refresh_from_db()
        self.assertEqual((lab_request.status, lab_request.reviewed_by), (LabRequest.Status.APPROVED, self.supervisor))

        self.login("sec")
        self.action(lab_request, "send")  # missing "checked against request" confirmation
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.APPROVED)
        self.action(lab_request, "send", checked="on")
        lab_request.refresh_from_db()
        self.assertEqual((lab_request.status, lab_request.sent_by), (LabRequest.Status.SENT, self.secretary))

        # The patient list shows the lab-work flag.
        listing = self.client.get("/patients/")
        self.assertEqual(listing.context["page_obj"][0].open_labs, 1)

        self.action(lab_request, "receive", checked="on")
        lab_request.refresh_from_db()
        self.assertEqual((lab_request.status, lab_request.received_by), (LabRequest.Status.RECEIVED, self.secretary))
        self.assertTrue(Notification.objects.filter(recipient=self.intern, title__contains=lab_request.number).exists())

        self.action(lab_request, "remake", notes="shade wrong")
        lab_request.refresh_from_db()
        self.assertEqual((lab_request.status, lab_request.remake_count), (LabRequest.Status.SENT, 1))
        self.action(lab_request, "receive", checked="on")
        self.action(lab_request, "deliver")
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.DELIVERED)
        self.assertEqual(self.patient.open_lab_requests().count(), 0)

        actions = list(LabRequestEvent.objects.filter(request=lab_request).values_list("action", flat=True))
        self.assertEqual(actions, ["created", "submitted", "approved", "sent", "received", "remake", "received", "delivered"])
        self.assertTrue(LabRequestEvent.objects.get(request=lab_request, action="sent").checked_against_request)

    def test_supervisor_can_return_with_reason(self):
        lab_request = LabRequest.objects.create(branch=self.branch, patient=self.patient, lab=self.lab, work_type=self.work,
                                                teeth="11", requested_by=self.intern, status=LabRequest.Status.PENDING_REVIEW)
        self.login("sup")
        self.action(lab_request, "return")
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.PENDING_REVIEW)  # reason required
        self.action(lab_request, "return", notes="add shade")
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.DRAFT)


class TreatmentStepTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.intern = make_user("intern", "intern")
        self.other = make_user("intern2", "intern")
        self.supervisor = make_user("sup", "supervisor")
        self.patient = make_patient(self.branch, assigned_intern=self.intern)
        self.step_type = TreatmentStepType.objects.get(name_en="Implant placement")

    def test_intern_records_own_step_and_supervisor_checks_it(self):
        self.client.login(username="intern", password=PASSWORD)
        self.client.post("/clinical/steps/new/", {
            "patient_lookup": self.patient.file_number, "step_type": self.step_type.pk, "teeth": "36",
            "performed_at": "2026-09-25T11:00", "performed_by": self.other.pk,  # ignored for interns
            "implant_system": "Straumann", "implant_size": "4.1x10",
        })
        step = TreatmentStep.objects.get()
        self.assertEqual(step.performed_by, self.intern)
        self.assertFalse(step.is_verified)
        self.assertEqual(self.client.post(f"/clinical/steps/{step.pk}/", {"grade": 5}).status_code, 403)

        self.client.login(username="sup", password=PASSWORD)
        self.client.post(f"/clinical/steps/{step.pk}/", {"grade": 4, "supervisor_comment": "good"})
        step.refresh_from_db()
        self.assertEqual((step.verified_by, step.grade), (self.supervisor, 4))

    def test_intern_cannot_record_for_other_interns_patient(self):
        other_patient = make_patient(self.branch, nid="28501010101235", phone="01112223334", assigned_intern=self.other)
        self.client.login(username="intern", password=PASSWORD)
        response = self.client.post("/clinical/steps/new/", {
            "patient_lookup": other_patient.file_number, "step_type": self.step_type.pk, "performed_at": "2026-09-25T11:00",
        })
        self.assertIn("patient_lookup", response.context["form"].errors)
        self.assertFalse(TreatmentStep.objects.exists())
