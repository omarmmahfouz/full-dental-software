from django.test import TestCase

from apps.charting.models import PlanItem, ToothChange, ToothState, TreatmentPlan
from apps.clinical.models import Lab, LabRequest, LabRequestEvent, LabWorkType, TreatmentStep, TreatmentStepType
from apps.core.models import Notification
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic


class LabWorkflowTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.supervisor = make_user("sup", "supervisor")
        self.secretary = make_user("sec", "secretary")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.lab = Lab.objects.first()
        self.work = LabWorkType.objects.first()

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def action(self, lab_request, action, **extra):
        return self.client.post(f"/clinical/lab/{lab_request.pk}/action/", {"action": action, **extra})

    def test_full_journey_with_reviews_and_notifications(self):
        self.login("dentist")
        self.client.post("/clinical/lab/new/", {
            "patient_lookup": self.patient.file_number, "dentist": self.dentist.pk, "lab": self.lab.pk,
            "work_type": self.work.pk, "teeth": "36", "units": 1, "submit_for_review": "1",
        })
        lab_request = LabRequest.objects.get()
        self.assertEqual(lab_request.dentist, self.dentist)
        self.assertEqual(lab_request.status, LabRequest.Status.PENDING_REVIEW)
        self.assertTrue(Notification.objects.filter(recipient=self.supervisor).exists())

        # The dentist cannot approve their own request, the secretary cannot send before review.
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
        self.assertTrue(Notification.objects.filter(recipient=self.dentist.user, title__contains=lab_request.number).exists())

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

    def test_cia_dentist_records_for_a_candidate_with_the_supervisor_name(self):
        candidate = make_dentist("candidate", kind="candidate", login=False)
        supervisor = make_dentist("sup-name", kind="supervisor", login=False)
        self.login("dentist")
        self.client.post("/clinical/lab/new/", {
            "patient_lookup": self.patient.file_number, "dentist": candidate.pk, "supervisor": supervisor.pk,
            "lab": self.lab.pk, "work_type": self.work.pk, "teeth": "36", "units": 1, "submit_for_review": "1",
        })
        lab_request = LabRequest.objects.get()
        # Supervisors do not log in: naming the supervisor counts as the review.
        self.assertEqual((lab_request.dentist, lab_request.supervisor, lab_request.status),
                         (candidate, supervisor, LabRequest.Status.APPROVED))
        self.assertEqual(lab_request.created_by, self.dentist.user)
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, title__contains=lab_request.number).exists())
        events = list(LabRequestEvent.objects.filter(request=lab_request).values_list("action", flat=True))
        self.assertEqual(events, ["created", "submitted", "approved"])

    def test_supervisor_can_return_with_reason(self):
        lab_request = LabRequest.objects.create(branch=self.branch, patient=self.patient, lab=self.lab, work_type=self.work,
                                                teeth="11", dentist=self.dentist, status=LabRequest.Status.PENDING_REVIEW)
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
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.other = make_dentist("dentist2", kind="fulltime")
        self.supervisor = make_user("sup", "supervisor")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.composite = TreatmentStepType.objects.get(name_en="Composite restoration")
        self.scaling = TreatmentStepType.objects.get(name_en="Scaling")

    def post_step(self, **data):
        payload = {"patient_lookup": self.patient.file_number, "performed_at": "2026-09-25T11:00",
                   "operator": self.dentist.pk, "update_chart": "on"}
        payload.update(data)
        return self.client.post("/clinical/steps/new/", payload)

    def test_dentist_records_own_step_and_supervisor_checks_it(self):
        self.client.login(username="dentist", password=PASSWORD)
        self.post_step(step_type=self.scaling.pk)
        step = TreatmentStep.objects.get()
        self.assertEqual((step.operator, step.created_by), (self.dentist, self.dentist.user))
        self.assertFalse(step.is_verified)
        self.assertEqual(self.client.post(f"/clinical/steps/{step.pk}/", {"grade": 5}).status_code, 403)

        self.client.login(username="sup", password=PASSWORD)
        self.client.post(f"/clinical/steps/{step.pk}/", {"grade": 4, "supervisor_comment": "good"})
        step.refresh_from_db()
        self.assertEqual((step.verified_by, step.grade), (self.supervisor, 4))

    def test_cia_dentist_records_the_candidates_work(self):
        candidate = make_dentist("candidate", kind="candidate", login=False)
        patient = make_patient(self.branch, nid="28501010101235", phone="01112223334", assigned_dentist=candidate)
        self.client.login(username="dentist", password=PASSWORD)
        page = self.client.get(f"/clinical/steps/new/?patient={patient.pk}")
        # The candidate is the operator, the CIA dentist writing it down assists.
        self.assertEqual((page.context["form"].initial["operator"], page.context["form"].initial["assistant"]),
                         (candidate, self.dentist))
        self.post_step(patient_lookup=patient.file_number, step_type=self.scaling.pk, operator=candidate.pk,
                       notes="Heavy calculus")
        step = TreatmentStep.objects.get()
        self.assertEqual((step.operator, step.created_by, step.notes), (candidate, self.dentist.user, "Heavy calculus"))
        # It shows in the CIA dentist's own treatment log, and in the candidate's file.
        self.assertEqual(list(self.client.get("/clinical/steps/").context["page_obj"]), [step])
        self.client.login(username="dentist2", password=PASSWORD)
        self.assertEqual(list(self.client.get("/clinical/steps/").context["page_obj"]), [])

    def test_restoration_updates_chart_and_ticks_plan(self):
        ToothState.objects.create(patient=self.patient, tooth=12, caries=True, caries_surfaces="MO")
        plan = TreatmentPlan.objects.create(patient=self.patient, status=TreatmentPlan.Status.APPROVED)
        item = PlanItem.objects.create(plan=plan, step_type=self.composite, teeth="12, 22")
        self.client.login(username="dentist", password=PASSWORD)
        response = self.post_step(step_type=self.composite.pk, teeth="12", surfaces="mo")
        self.assertRedirects(response, f"/chart/patient/{self.patient.pk}/", fetch_redirect_response=False)
        state = ToothState.objects.get(patient=self.patient, tooth=12)
        self.assertEqual((state.caries, state.filled, state.filling_surfaces, state.filling_material),
                         (False, True, "MO", "composite"))
        step = TreatmentStep.objects.get()
        self.assertTrue(step.chart_updated)
        self.assertEqual(ToothChange.objects.get().treatment, step)
        item.refresh_from_db()
        self.assertEqual((item.status, item.teeth, item.done_treatment), (PlanItem.Status.DONE, "12", step))
        rest = PlanItem.objects.get(status=PlanItem.Status.PLANNED)  # 22 is still to do
        self.assertEqual(rest.teeth, "22")
        self.post_step(step_type=self.composite.pk, teeth="22")
        rest.refresh_from_db()
        self.assertEqual(rest.status, PlanItem.Status.DONE)
        plan.refresh_from_db()
        self.assertEqual(plan.status, TreatmentPlan.Status.COMPLETED)

    def test_chart_left_alone_when_not_confirmed(self):
        ToothState.objects.create(patient=self.patient, tooth=12, caries=True)
        self.client.login(username="dentist", password=PASSWORD)
        self.post_step(step_type=self.composite.pk, teeth="12", update_chart="")
        self.assertTrue(ToothState.objects.get(patient=self.patient, tooth=12).caries)
        self.assertFalse(TreatmentStep.objects.get().chart_updated)

    def test_teeth_required_for_treatments_that_change_the_chart(self):
        self.client.login(username="dentist", password=PASSWORD)
        response = self.post_step(step_type=self.composite.pk)
        self.assertIn("teeth", response.context["form"].errors)


class OutsideRequestTests(TestCase):
    def test_cbct_and_medical_lab_requests_print_for_the_patient(self):
        from apps.clinical.models import OutsideRequest
        from apps.core.testing import make_patient

        branch = setup_clinic()
        patient = make_patient(branch)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        url = f"/clinical/requests/new/?patient={patient.pk}&kind=cbct"
        response = self.client.post(url, {"requested_on": "01/09/2026", "region": "teeth", "teeth": "36 37",
                                           "purposes": ["implant", "guided"]})
        cbct = OutsideRequest.objects.get(kind="cbct")
        self.assertRedirects(response, cbct.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(cbct.teeth, "36, 37")
        page = self.client.get(cbct.get_absolute_url())
        self.assertContains(page, "ciapts@gmail.com")
        self.assertContains(page, "DICOM")
        response = self.client.post(f"/clinical/requests/new/?patient={patient.pk}&kind=medical_lab",
                                    {"requested_on": "01/09/2026"})
        self.assertIn("tests", response.context["form"].errors)
        self.client.post(f"/clinical/requests/new/?patient={patient.pk}&kind=medical_lab",
                         {"requested_on": "01/09/2026", "tests": ["cbc", "hba1c"]})
        lab = OutsideRequest.objects.get(kind="medical_lab")
        self.assertNotContains(self.client.get(lab.get_absolute_url()), "ciapts@gmail.com")
        self.assertEqual(len(lab.test_labels()), 2)
