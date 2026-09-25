import shutil
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.patients.models import Lead, Patient, PatientDocument, PatientRelation, ReferralSource
from apps.scheduling.models import Appointment
from django.utils import timezone

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class PatientRegistrationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("dentist")
        self.client.login(username="sec", password=PASSWORD)
        self.facebook = ReferralSource.objects.get(name_en="Facebook")

    def form_data(self, **overrides):
        data = {
            "full_name": "محمد أحمد علي حسن",
            "id_type": "nid",
            "national_id": "29001150101234",
            "phone_primary": "01001234567",
            "preferred_phone": "primary",
            "missing_teeth": "single",
            "referral_source": self.facebook.pk,
            "assigned_dentist": self.dentist.pk,
        }
        data.update(overrides)
        return data

    def test_register_patient_with_id_scan(self):
        data = self.form_data(id_front=SimpleUploadedFile("id.jpg", b"fake-image", content_type="image/jpeg"))
        response = self.client.post("/patients/new/", data)
        patient = Patient.objects.get()
        self.assertRedirects(response, f"/patients/{patient.pk}/", fetch_redirect_response=False)
        self.assertEqual(patient.file_number, f"CIA-{patient.pk:05d}")
        self.assertEqual(patient.birth_date, date(1990, 1, 15))  # read from the national ID
        self.assertEqual(patient.gender, "M")
        self.assertEqual(patient.assigned_dentist, self.dentist)
        self.assertEqual(patient.created_by, self.secretary)
        document = PatientDocument.objects.get()
        self.assertEqual(document.kind, PatientDocument.Kind.ID_FRONT)
        # The scan is served only through the protected view.
        self.assertEqual(self.client.get(document.file.url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(document.file.url).status_code, 302)

    def test_duplicate_national_id_is_rejected(self):
        existing = make_patient(self.branch, nid="29001150101234", phone="01112223334")
        response = self.client.post("/patients/new/", self.form_data())
        self.assertEqual(Patient.objects.count(), 1)
        self.assertContains(response, existing.file_number)

    def test_duplicate_primary_phone_is_rejected_whatever_the_format(self):
        make_patient(self.branch, nid="28501010101235", phone="01001234567")
        for typed in ["+20 100 123 4567", "٠١٠٠١٢٣٤٥٦٧"]:
            response = self.client.post("/patients/new/", self.form_data(phone_primary=typed))
            self.assertEqual(Patient.objects.count(), 1, typed)
            self.assertIn("phone_primary", response.context["form"].errors)

    def test_invalid_national_id(self):
        response = self.client.post("/patients/new/", self.form_data(national_id="123"))
        self.assertIn("national_id", response.context["form"].errors)

    def test_referral_by_patient_requires_the_referring_patient(self):
        by_patient = ReferralSource.objects.get(asks_for_patient=True)
        referrer = make_patient(self.branch, nid="28501010101235", phone="01112223334")
        response = self.client.post("/patients/new/", self.form_data(referral_source=by_patient.pk))
        self.assertIn("referred_by_lookup", response.context["form"].errors)
        self.client.post("/patients/new/", self.form_data(referral_source=by_patient.pk, referred_by_lookup="01112223334"))
        self.assertEqual(Patient.objects.get(national_id="29001150101234").referred_by, referrer)

    def test_relative_link_on_registration(self):
        relative = make_patient(self.branch, nid="28501010101235", phone="01112223334")
        self.client.post("/patients/new/", self.form_data(relative_lookup=relative.file_number, relative_relation="sibling"))
        patient = Patient.objects.get(national_id="29001150101234")
        relation = PatientRelation.objects.get()
        self.assertEqual((relation.patient, relation.related_patient), (patient, relative))
        self.assertEqual(relative.relations()[0][0], patient)

    def test_convert_lead_to_patient(self):
        lead = Lead.objects.create(branch=self.branch, full_name="متصل", phone_primary="01001234567", missing_teeth="full_arch")
        page = self.client.get(f"/patients/new/?lead={lead.pk}")
        self.assertEqual(page.context["form"].initial["phone_primary"], "01001234567")
        self.client.post("/patients/new/", self.form_data(lead=lead.pk))
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.CONVERTED)
        self.assertEqual(lead.converted_patient.national_id, "29001150101234")

    def test_lead_with_phone_of_registered_patient_is_rejected(self):
        make_patient(self.branch, phone="01001234567")
        response = self.client.post("/patients/calls/new/", {
            "full_name": "x", "phone_primary": "01001234567", "preferred_phone": "primary",
            "missing_teeth": "single", "status": "new",
        })
        self.assertIn("phone_primary", response.context["form"].errors)
        self.assertFalse(Lead.objects.exists())

    def test_log_call_updates_lead(self):
        lead = Lead.objects.create(branch=self.branch, full_name="متصل", phone_primary="01001234567")
        self.client.post(f"/patients/calls/{lead.pk}/log/", {"called_at": "25/09/2026 10:00", "outcome": "no_answer"})
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.FOLLOW_UP)
        self.assertEqual(lead.calls.count(), 1)

    def test_search_by_phone_opens_the_file(self):
        patient = make_patient(self.branch)
        response = self.client.get("/patients/", {"q": "+20 100 123 4567"})
        self.assertRedirects(response, patient.get_absolute_url(), fetch_redirect_response=False)


class DentistAccessTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.other_dentist = make_dentist("dentist2", kind="fulltime")
        self.mine = make_patient(self.branch, assigned_dentist=self.dentist)
        self.not_mine = make_patient(self.branch, nid="28501010101235", phone="01112223334",
                                     assigned_dentist=self.other_dentist)
        self.client.login(username="dentist", password=PASSWORD)

    def test_cia_dentist_sees_every_patient_and_can_filter_their_own(self):
        # They record the work of the course candidates, who do not log in.
        self.assertEqual(self.client.get(self.not_mine.get_absolute_url()).status_code, 200)
        self.assertEqual(len(self.client.get("/patients/").context["page_obj"]), 2)
        self.assertEqual(list(self.client.get("/patients/", {"mine": "on"}).context["page_obj"]), [self.mine])

    def test_my_patients_include_patients_booked_with_them(self):
        Appointment.objects.create(branch=self.branch, patient=self.not_mine, dentist=self.dentist, scheduled_at=timezone.now())
        self.assertEqual(len(self.client.get("/patients/", {"mine": "on"}).context["page_obj"]), 2)

    def test_dentist_cannot_register_or_open_call_list(self):
        self.assertEqual(self.client.get("/patients/new/").status_code, 403)
        self.assertEqual(self.client.get("/patients/calls/").status_code, 403)

    def test_stock_manager_sees_no_patients(self):
        make_user("stock", "stock")
        self.client.login(username="stock", password=PASSWORD)
        self.assertEqual(self.client.get(self.mine.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get("/patients/").status_code, 403)


class PlanFinderAndCallListTests(TestCase):
    def setUp(self):
        from apps.charting.models import PlanItem, TreatmentPlan
        from apps.clinical.models import TreatmentStepType

        self.branch = setup_clinic()
        self.head = make_user("head", "head_cia")
        self.secretary = make_user("sec", "secretary")
        guided = TreatmentStepType.objects.get(name_en="Guided implant surgery")
        simple = TreatmentStepType.objects.get(name_en="Implant placement")
        self.p1 = make_patient(self.branch)
        self.p2 = make_patient(self.branch, nid="28501010101235", phone="01112223334")
        self.p3 = make_patient(self.branch, nid="28501010101236", phone="01112223335")
        for patient, step_type, difficulty in [(self.p1, guided, "simple"), (self.p2, guided, "moderate"),
                                               (self.p3, simple, "simple")]:
            plan = TreatmentPlan.objects.create(patient=patient, difficulty=difficulty)
            PlanItem.objects.create(plan=plan, step_type=step_type, teeth="36")
        self.guided = guided

    def find(self, **params):
        return self.client.get("/chart/plans/", params)

    def found(self, **params):
        return {plan.patient for plan, *_rest in self.find(**params).context["page_obj"]}

    def test_find_plans_by_procedure_and_difficulty(self):
        self.client.login(username="head", password=PASSWORD)
        self.assertEqual(self.found(), {self.p1, self.p2, self.p3})
        self.assertEqual(self.found(procedures=self.guided.pk), {self.p1, self.p2})
        self.assertEqual(self.found(procedures=self.guided.pk, difficulty="simple"), {self.p1})
        Appointment.objects.create(branch=self.branch, patient=self.p1, scheduled_at=timezone.now() + timedelta(days=2))
        self.assertEqual(self.found(procedures=self.guided.pk, no_appointment="on"), {self.p2})
        csv = self.find(procedures=self.guided.pk, export="csv").content.decode("utf-8-sig")
        self.assertEqual(len(csv.strip().splitlines()), 3)
        # The reasons sent to the reception are in Arabic, whatever the sender's language.
        page = self.find(procedures=self.guided.pk)
        self.assertIn((self.p1, "زرع بدليل جراحي 36"), page.context["call_rows"])
        self.assertIn("زرع بدليل جراحي", page.context["call_title"])
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.find().status_code, 403)

    def test_send_to_reception_and_record_answers(self):
        from apps.core.models import Notification
        from apps.patients.models import CallList, CallListEntry

        self.client.login(username="head", password=PASSWORD)
        response = self.client.post("/patients/to-call/new/", {
            "title": "Guided cases", "message": "Book the surgery day", "patient": [self.p1.pk, self.p2.pk],
            f"reason_{self.p1.pk}": "Guided implant surgery 36", "next": "/chart/plans/",
        })
        call_list = CallList.objects.get()
        self.assertRedirects(response, call_list.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(call_list.entries.count(), 2)
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, title__contains="Guided cases").exists())

        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["call_lists"][0], call_list)
        page = self.client.get(call_list.get_absolute_url())
        self.assertContains(page, "Guided implant surgery 36")
        self.assertContains(page, "الضرس الأول السفلي الأيسر")  # 36 explained to the secretary
        for entry, outcome in zip(call_list.entries.all(), ["booked", "no_answer"]):
            self.client.post(f"/patients/to-call/answer/{entry.pk}/", {f"e{entry.pk}-outcome": outcome,
                                                                       f"e{entry.pk}-response": "ok"})
        first = call_list.entries.get(patient=self.p1)
        self.assertEqual((first.outcome, first.called_by, first.attempts), ("booked", self.secretary, 1))
        self.assertEqual(call_list.progress, (2, 2))
        # The head of CIA is told when every patient was called.
        self.assertTrue(Notification.objects.filter(recipient=self.head, title__contains="Guided cases").exists())
        self.assertEqual(self.client.post("/patients/to-call/new/", {"title": "x", "patient": [self.p1.pk]}).status_code, 403)
        self.assertEqual(CallListEntry.objects.filter(outcome="pending").count(), 0)


class PatientSearchTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.patient = make_patient(self.branch, name="أحمد فاطمة مصطفى", nid="29001011234567", phone="01001234567")
        make_patient(self.branch, name="سارة علي", nid="29002021234568", phone="01101234567")
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)

    def test_suggestions_ignore_arabic_spelling_variants(self):
        for typed in ("احمد", "فاطمه مصطفي", "0100123", self.patient.file_number):
            results = self.client.get("/patients/lookup/", {"q": typed}).json()["results"]
            self.assertEqual([r["value"] for r in results], [self.patient.file_number], typed)
        self.assertEqual(self.client.get("/patients/lookup/", {"q": "x"}).json()["results"], [])

    def test_booking_takes_the_chosen_patient_and_a_dd_mm_yyyy_date(self):
        from apps.scheduling.models import Appointment

        day = timezone.localdate() + timedelta(days=2)
        response = self.client.post("/schedule/appointments/new/", {
            "patient_lookup": self.patient.file_number, "scheduled_at_0": day.strftime("%d/%m/%Y"),
            "scheduled_at_1": "10:15", "duration_minutes": "30",
        })
        appointment = Appointment.objects.get()
        self.assertRedirects(response, appointment.get_absolute_url(), fetch_redirect_response=False)
        local = timezone.localtime(appointment.scheduled_at)
        self.assertEqual((local.date(), local.strftime("%H:%M"), appointment.patient), (day, "10:15", self.patient))
        page = self.client.get(f"/schedule/appointments/{appointment.pk}/edit/").content.decode()
        self.assertIn(day.strftime("%d/%m/%Y"), page)
        self.assertIn('value="10:15" selected', page)


class TreatmentExplanationTests(TestCase):
    def test_the_patient_file_explains_plans_and_treatments_in_arabic(self):
        from apps.charting.models import PlanItem, TreatmentPlan
        from apps.charting.teeth import teeth_ar
        from apps.clinical.models import TreatmentStep, TreatmentStepType

        self.assertEqual(teeth_ar("11-12"), "12 (القاطع الجانبي العلوي الأيمن)، 11 (القاطع الأوسط العلوي الأيمن)")
        branch = setup_clinic()
        patient = make_patient(branch)
        guided = TreatmentStepType.objects.get(name_en="Guided implant surgery")
        plan = TreatmentPlan.objects.create(patient=patient)
        PlanItem.objects.create(plan=plan, step_type=guided, teeth="46")
        scaling = TreatmentStepType.objects.get(name_en="Scaling")
        TreatmentStep.objects.create(patient=patient, step_type=scaling, performed_at=timezone.now())
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get(f"/patients/{patient.pk}/")
        for text in ("زرع بدليل جراحي", guided.description_ar, "الضرس الأول السفلي الأيمن", scaling.description_ar):
            self.assertContains(page, text)
        self.assertNotContains(page, "/clinical/steps/")  # the secretary reads it here, without the treatment log


class PatientDataTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.source = ReferralSource.objects.get(name_en="Facebook")

    def test_old_files_keep_their_date_and_the_governorate_comes_from_the_id(self):
        self.client.post("/patients/new/", {
            "full_name": "محمد أحمد", "id_type": "nid", "national_id": "29001152101234", "phone_primary": "01001234567",
            "preferred_phone": "primary", "missing_teeth": "single", "referral_source": self.source.pk,
            "registered_on": "03/02/2019",
        })
        patient = Patient.objects.get()
        self.assertEqual((patient.registered_on, patient.governorate), (date(2019, 2, 3), "21"))  # Giza
        self.assertEqual(Patient._meta.get_field("governorate").choices[0][0], "01")

    def test_out_needs_a_reason(self):
        from apps.patients.models import OutReason

        patient = make_patient(self.branch)
        data = {"full_name": patient.full_name, "id_type": "nid", "national_id": patient.national_id,
                "phone_primary": patient.phone_primary, "preferred_phone": "primary", "missing_teeth": "single",
                "referral_source": self.source.pk, "status": "out"}
        response = self.client.post(f"/patients/{patient.pk}/edit/", data)
        self.assertIn("out_reason", response.context["form"].errors)
        self.assertTrue(OutReason.objects.exists())

    def test_the_call_list_keeps_who_called_first(self):
        for name, phone, day in [("Late caller", "01001111111", ""), ("Early caller", "01002222222", "01/09/2026")]:
            self.client.post("/patients/calls/new/", {"full_name": name, "phone_primary": phone,
                                                      "preferred_phone": "primary", "missing_teeth": "single",
                                                      "status": "new", "first_call_on": day})
        late = Lead.objects.get(full_name="Late caller")
        self.assertEqual(late.first_call_on, timezone.localdate())
        page = self.client.get("/patients/calls/", {"due": "1"})
        self.assertEqual([lead.full_name for lead in page.context["page_obj"]], ["Early caller", "Late caller"])


class PhoneCheckTests(TestCase):
    def test_wrong_length_and_duplicates_are_told_while_typing(self):
        branch = setup_clinic()
        patient = make_patient(branch, name="سارة علي", phone="01001234567")
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)

        def check(**params):
            return self.client.get("/patients/phone-check/", params).json()

        self.assertIn("10", check(phone="0100123456")["message"])
        self.assertIn("سارة علي", check(phone="01001234567")["message"])
        self.assertEqual(check(phone="01001234567", pk=patient.pk), {})  # its own number
        self.assertEqual(check(phone="01101234567"), {})
        self.assertEqual(check(phone="0223456789", field="secondary"), {})  # a landline is fine as mobile 2
        response = self.client.post("/patients/new/", {"full_name": "x", "phone_primary": "0100"})
        self.assertContains(response, "data-show-on-load")  # the errors open in a box


@override_settings(MEDIA_ROOT=MEDIA)
class IdCardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @staticmethod
    def photo(size=(1200, 1000), card=(300, 250, 900, 628), name="id.jpg"):
        """A grey table with a light blue card on it, as a phone photo would show."""
        import io

        from PIL import Image, ImageDraw

        image = Image.new("RGB", size, (90, 90, 95))
        draw = ImageDraw.Draw(image)
        draw.rectangle(card, fill=(200, 225, 240))
        draw.text((card[0] + 40, card[1] + 40), "29001011234567", fill=(0, 0, 0))
        output = io.BytesIO()
        image.save(output, "JPEG")
        return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg")

    def test_the_card_is_cut_out_and_the_original_kept(self):
        from PIL import Image

        branch = setup_clinic()
        patient = make_patient(branch)
        document = PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.ID_FRONT, file=self.photo())
        with Image.open(document.file.path) as card:
            self.assertTrue(590 <= card.width <= 640 and 360 <= card.height <= 410, card.size)
        self.assertTrue(document.original)
        # A photo that is already just the card is kept as it is.
        plain = PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.ID_BACK,
                                               file=self.photo(size=(856, 540), card=(0, 0, 856, 540)))
        self.assertFalse(plain.original)
        # A card photographed standing up is turned to lie flat.
        standing = PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.ID_BACK,
                                                  file=self.photo(size=(1000, 1200), card=(250, 300, 628, 900)))
        with Image.open(standing.file.path) as card:
            self.assertGreater(card.width, card.height)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/patients/{patient.pk}/documents/{document.pk}/rotate/", {"way": "right"})
        document.refresh_from_db()
        with Image.open(document.file.path) as card:
            self.assertGreater(card.height, card.width)
