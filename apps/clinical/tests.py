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
        self.action(lab_request, "send", checked="on")  # physical work: first taken from the dentist
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.APPROVED)
        self.action(lab_request, "collect")
        lab_request.refresh_from_db()
        self.assertEqual((lab_request.status, lab_request.collected_by), (LabRequest.Status.COLLECTED, self.secretary))
        self.action(lab_request, "send")  # missing "checked against request" confirmation
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.COLLECTED)
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
        self.assertEqual(actions, ["created", "submitted", "approved", "collected", "sent", "received", "remake", "received",
                                   "delivered"])
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


class LabDetailsTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.secretary = make_user("sec", "secretary")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.lab = Lab.objects.first()
        self.zirconia = LabWorkType.objects.get(name_en="Zirconia crown")

    def test_digital_work_shade_guide_usual_days_and_fitting(self):
        from datetime import timedelta

        from django.utils import timezone

        supervisor = make_dentist("sup", kind="supervisor", login=False)
        self.client.login(username="dentist", password=PASSWORD)
        page = self.client.get(f"/clinical/lab/new/?patient={self.patient.pk}")
        self.assertEqual(page.context["form"]["patient_lookup"].value(),
                         f"{self.patient.file_number} — {self.patient.full_name}")  # the name is already there
        response = self.client.post(f"/clinical/lab/new/?patient={self.patient.pk}", {
            "patient_lookup": f"{self.patient.file_number} — {self.patient.full_name}", "dentist": self.dentist.pk,
            "supervisor": supervisor.pk, "lab": self.lab.pk, "work_type": self.zirconia.pk, "work_form": "digital",
            "teeth": "36", "units": 1, "shade_guide": "classical", "shade": "2M2", "submit_for_review": "1"})
        self.assertIn("shade", response.context["form"].errors)  # 2M2 is a 3D-Master shade
        self.client.post(f"/clinical/lab/new/?patient={self.patient.pk}", {
            "patient_lookup": self.patient.file_number, "dentist": self.dentist.pk, "supervisor": supervisor.pk,
            "lab": self.lab.pk, "work_type": self.zirconia.pk, "work_form": "digital", "teeth": "36", "units": 1,
            "shade": "A3", "submit_for_review": "1"})
        lab_request = LabRequest.objects.get()
        self.assertEqual((lab_request.shade_guide, lab_request.status), ("classical", LabRequest.Status.APPROVED))
        self.assertEqual(lab_request.stage, LabRequest.Stage.FINAL)  # not chosen: the final work
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/clinical/lab/{lab_request.pk}/action/", {"action": "send", "checked": "on"})  # no collection
        lab_request.refresh_from_db()
        self.assertEqual(lab_request.status, LabRequest.Status.SENT)
        self.assertEqual(lab_request.due_date, timezone.localdate() + timedelta(days=self.zirconia.default_days))
        self.client.post(f"/clinical/lab/{lab_request.pk}/action/", {"action": "receive", "checked": "on"})
        page = self.client.get(f"/clinical/lab/{lab_request.pk}/")
        self.assertIn(f"patient={self.patient.pk}", page.context["fitting_url"])
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, url=lab_request.get_absolute_url())
                        .exists())


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
        step = TreatmentStep.objects.get()  # a filling asks for its photos before and after (round 10)
        self.assertRedirects(response, f"/clinical/steps/{step.pk}/", fetch_redirect_response=False)
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


    def test_dentist_adds_the_bill_for_the_reception(self):
        from decimal import Decimal

        from apps.billing.models import Bill, Service

        filling = Service.objects.get(name_en="Filling")
        self.client.login(username="dentist", password=PASSWORD)
        self.post_step(step_type=self.composite.pk, teeth="12", bill_service=filling.pk, bill_price="450")
        bill = Bill.objects.get()
        self.assertEqual((bill.source, bill.dentist, bill.patient), ("dentist", self.dentist, self.patient))
        self.assertEqual((bill.totals()["left"], bill.charges.get().teeth), (Decimal("450"), "12"))


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

    def test_cbct_requested_opens_the_request_and_done_opens_the_scan(self):
        from apps.charting.models import Examination
        from apps.clinical.models import OutsideRequest

        branch = setup_clinic()
        patient = make_patient(branch)
        make_dentist("dentist", kind="fulltime")
        self.client.login(username="dentist", password=PASSWORD)
        # Ticking "CBCT requested" on the examination opens the CBCT request, then goes on with the file.
        response = self.client.post(f"/chart/patient/{patient.pk}/exam/new/?flow=1", {
            "exam_date": "01/09/2026", "cbct_requested": "on", "flow": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/clinical/requests/new/", response.url)
        self.assertIn("kind=cbct", response.url)
        response = self.client.post(response.url, {"requested_on": "01/09/2026", "region": "lower"})
        cbct = OutsideRequest.objects.get()
        self.assertIn(f"/clinical/requests/{cbct.pk}/?next=", response.url)
        page = self.client.get(response.url)
        # "print it, then go on": the next step of the file, the impression or diagnostic scan (round 10)
        self.assertContains(page, f"/patients/{patient.pk}/records/?step=impression&amp;flow=1")
        self.assertNotContains(page, "?where=done_here")  # no CBCT machine at this place
        branch.has_cbct = True
        branch.save()
        self.assertContains(self.client.get(cbct.get_absolute_url()), "?where=done_here")
        response = self.client.post(f"/clinical/requests/{cbct.pk}/done/", {
            "where": "done_here", "done_on": "02/09/2026", "location": r"\\CIA-SERVER\CBCT\CIA-00001"})
        cbct.refresh_from_db()
        self.assertEqual((cbct.status, str(cbct.done_on)), ("done_here", "2026-09-02"))
        self.assertEqual(cbct.result.location, r"\\CIA-SERVER\CBCT\CIA-00001")
        self.assertTrue(Examination.objects.get().cbct_done)
        exam_page = self.client.get(Examination.objects.get().get_absolute_url())
        self.assertContains(exam_page, "CIA-SERVER")
        self.assertContains(exam_page, cbct.get_absolute_url())
        self.assertContains(self.client.get(f"/patients/{patient.pk}/"), "CIA-SERVER")


class StepKindsTests(TestCase):
    """Round 10: the steps grouped by the kind of work (endodontics: access, cleaning, obturation, single visit...),
    each with the photos and periapical X-rays it should have."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self.media.enable()
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.client.login(username="dentist", password=PASSWORD)

    def tearDown(self):
        import shutil

        from django.conf import settings

        root = settings.MEDIA_ROOT
        self.media.disable()
        shutil.rmtree(root, ignore_errors=True)

    def test_the_kinds_and_their_steps(self):
        endo = {t.name_en for t in TreatmentStepType.objects.filter(group="endo")}
        self.assertTrue({"Endo: access opening", "Endo: access, cleaning and shaping", "Endo: obturation",
                         "Endo: all in a single visit"} <= endo)
        single = TreatmentStepType.objects.get(name_en="Endo: all in a single visit")
        self.assertEqual([code for code, _label in single.shot_list()], ["pa_before", "pa_working", "pa_cone", "pa_after"])
        self.assertEqual(single.chart_effect, "rct")
        page = self.client.get(f"/clinical/steps/new/?patient={self.patient.pk}&group=endo")
        groups = {g["code"]: g for g in page.context["step_groups"]}
        self.assertIn(single.pk, [t["id"] for t in groups["endo"]["types"]])
        self.assertContains(page, 'data-chosen-group="endo"')

    def test_the_xrays_of_a_step(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.charting.models import ClinicalPhoto

        access = TreatmentStepType.objects.get(name_en="Endo: access, cleaning and shaping")
        response = self.client.post("/clinical/steps/new/", {
            "patient_lookup": self.patient.file_number, "performed_at": "2026-09-25T11:00", "operator": self.dentist.pk,
            "step_type": access.pk, "teeth": "36"})
        step = TreatmentStep.objects.get()
        self.assertRedirects(response, f"/clinical/steps/{step.pk}/", fetch_redirect_response=False)
        page = self.client.get(f"/clinical/steps/{step.pk}/")
        self.assertEqual([s["code"] for s in page.context["shots"]], ["pa_before", "pa_working"])
        picture = SimpleUploadedFile("pa.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        self.client.post(f"/clinical/steps/{step.pk}/photo/", {"shot": "pa_working", "file": picture})
        photo = ClinicalPhoto.objects.get()
        self.assertEqual((photo.treatment_step, photo.shot, photo.stage, photo.teeth), (step, "pa_working", "treatment", "36"))
        page = self.client.get(f"/clinical/steps/{step.pk}/")
        self.assertEqual([len(s["photos"]) for s in page.context["shots"]], [0, 1])
        text = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        self.client.post(f"/clinical/steps/{step.pk}/photo/", {"shot": "pa_before", "file": text})
        self.assertEqual(ClinicalPhoto.objects.count(), 1)  # only photos or PDF


class Round13RestorativeFinderTests(TestCase):
    """Restorative work on its own page: the treatment log without surgery, grouped for statistics."""

    def setUp(self):
        from apps.clinical.models import TreatmentStep, TreatmentStepType
        from apps.core.testing import make_dentist, make_patient

        self.branch = setup_clinic()
        make_user("head", "head_cia")
        self.dentist = make_dentist("dentist", kind="fulltime")
        patient = make_patient(self.branch)
        types = {t.group: t for t in TreatmentStepType.objects.all()}
        for group, teeth in (("fillings", "36"), ("fillings", "11"), ("endo", "46"), ("surgery", "36")):
            TreatmentStep.objects.create(patient=patient, step_type=types[group], teeth=teeth, operator=self.dentist)

    def test_restorative_work_is_found_and_grouped_apart_from_surgery(self):
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/clinical/restorative-finder/").status_code, 403)
        self.client.login(username="head", password=PASSWORD)
        page = self.client.get("/clinical/restorative-finder/")
        self.assertEqual(page.context["overall"]["steps"], 3)  # the surgery is not restorative work
        kinds = {row["code"]: row["steps"] for row in page.context["kinds"]}
        self.assertEqual(kinds, {"fillings": 2, "endo": 1})
        grouped = self.client.get("/clinical/restorative-finder/", {"group_by": "region"}).context["groups"]
        self.assertEqual({g["key"]: g["steps"] for g in grouped}, {"Posterior": 2, "Anterior": 1})
        self.assertEqual(self.client.get("/clinical/restorative-finder/", {"groups": "endo"}).context["overall"]["steps"], 1)
        self.assertEqual(self.client.get("/clinical/restorative-finder/", {"teeth": "11"}).context["overall"]["steps"], 1)
        csv = self.client.get("/clinical/restorative-finder/", {"export": "csv"}).content.decode("utf-8-sig")
        self.assertEqual(len(csv.strip().splitlines()), 4)


class Round15LabListTests(TestCase):
    """Round 15: the lab requests have a menu entry of their own, and tabs for the plan (in work) and the done."""

    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.patient = make_patient(self.branch)
        lab, work = Lab.objects.first(), LabWorkType.objects.first()
        for status in ("approved", "sent", "delivered"):
            LabRequest.objects.create(branch=self.branch, patient=self.patient, lab=lab, work_type=work, teeth="36",
                                      status=status)
        self.client.login(username="sec", password=PASSWORD)

    def test_tabs_and_menu_count(self):
        response = self.client.get("/clinical/lab/")
        tabs = {tab["code"]: tab["count"] for tab in response.context["part_tabs"]}
        self.assertEqual(tabs, {"": 3, "planned": 2, "done": 1})
        self.assertEqual(response.context["lab_to_act"], 1)  # approved: to take and send
        self.assertEqual(len(self.client.get("/clinical/lab/?part=planned").context["page_obj"]), 2)
        done = self.client.get("/clinical/lab/?part=done").context["page_obj"]
        self.assertEqual([lr.status for lr in done], ["delivered"])
