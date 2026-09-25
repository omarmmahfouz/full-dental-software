import shutil
import tempfile
from datetime import date

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
        self.client.post(f"/patients/calls/{lead.pk}/log/", {
            "called_at": "2026-09-25T10:00", "outcome": "no_answer", "next_call_at": "2026-09-26T12:00",
        })
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.FOLLOW_UP)
        self.assertEqual(lead.calls.count(), 1)
        self.assertIsNotNone(lead.next_call_at)

    def test_search_by_phone_opens_the_file(self):
        patient = make_patient(self.branch)
        response = self.client.get("/patients/", {"q": "+20 100 123 4567"})
        self.assertRedirects(response, patient.get_absolute_url(), fetch_redirect_response=False)


class DentistAccessTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist")
        self.other_dentist = make_dentist("dentist2")
        self.mine = make_patient(self.branch, assigned_dentist=self.dentist)
        self.not_mine = make_patient(self.branch, nid="28501010101235", phone="01112223334",
                                     assigned_dentist=self.other_dentist)
        self.client.login(username="dentist", password=PASSWORD)

    def test_dentist_sees_only_own_patients(self):
        self.assertEqual(self.client.get(self.mine.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.not_mine.get_absolute_url()).status_code, 403)
        listing = self.client.get("/patients/")
        self.assertEqual(list(listing.context["page_obj"]), [self.mine])

    def test_dentist_sees_patient_booked_with_them(self):
        Appointment.objects.create(branch=self.branch, patient=self.not_mine, dentist=self.dentist, scheduled_at=timezone.now())
        self.assertEqual(self.client.get(self.not_mine.get_absolute_url()).status_code, 200)

    def test_dentist_sees_patients_of_surgeries_they_instructed(self):
        from apps.surgery.models import Surgery

        instructor = make_dentist("sup", kind="supervisor")
        Surgery.objects.create(branch=self.branch, patient=self.not_mine, operator_1=self.other_dentist, instructor=instructor)
        self.client.login(username="sup", password=PASSWORD)
        self.assertEqual(self.client.get(self.not_mine.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(self.mine.get_absolute_url()).status_code, 403)

    def test_dentist_cannot_register_or_open_call_list(self):
        self.assertEqual(self.client.get("/patients/new/").status_code, 403)
        self.assertEqual(self.client.get("/patients/calls/").status_code, 403)
