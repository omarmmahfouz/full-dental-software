from decimal import Decimal

from django.test import TestCase

from apps.charting.models import Examination
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.prescriptions.models import Drug, Prescription
from apps.prescriptions.services import best_template, surgery_procedures
from apps.surgery.models import ImplantSystem, Surgery, SurgerySite


class PrescriptionTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.dentist)
        SurgerySite.objects.create(surgery=self.surgery, tooth=26, simple_implant=True, open_sinus=True,
                                   implant_system=ImplantSystem.objects.first(), implant_diameter=Decimal("4.5"),
                                   implant_length=Decimal("10"))
        self.client.login(username="dentist", password=PASSWORD)

    def test_the_prescription_fits_the_surgery_and_allergy(self):
        procedures = surgery_procedures(self.surgery)
        self.assertEqual(procedures, {"simple_implant", "open_sinus"})
        self.assertEqual(best_template(procedures).name_en, "After sinus lift")
        self.assertEqual(best_template(procedures, allergic=True).name_en, "After sinus lift — penicillin allergy")
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/new/?surgery={self.surgery.pk}")
        names = [Drug.objects.get(pk=line["drug"]).name for line in page.context["formset"].initial]
        self.assertEqual(names, ["Augmentin 1 g", "Brufen 400 mg", "Hexitol mouthwash", "Otrivin 0.1%"])
        Examination.objects.create(patient=self.patient, allergy_penicillin=True)
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/new/?surgery={self.surgery.pk}")
        self.assertTrue(page.context["allergic"])
        self.assertEqual(Drug.objects.get(pk=page.context["formset"].initial[0]["drug"]).name, "Dalacin C 300 mg")

    def test_write_and_print_with_an_interchangeable_brand(self):
        megamox = Drug.objects.get(name="Megamox 1 g")
        response = self.client.post(f"/prescriptions/patient/{self.patient.pk}/new/", {
            "surgery": self.surgery.pk, "prescribed_on": "2026-09-25", "dentist": self.dentist.pk, "notes": "",
            "lines-TOTAL_FORMS": 2, "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000,
            "lines-0-drug": megamox.pk, "lines-0-dose": "", "lines-1-drug": "", "lines-1-dose": "",
        })
        prescription = Prescription.objects.get()
        self.assertRedirects(response, f"/prescriptions/{prescription.pk}/", fetch_redirect_response=False)
        line = prescription.lines.get()
        self.assertEqual((line.drug, line.dose), (megamox, megamox.group.dose))  # the group's usual dose
        page = self.client.get(f"/prescriptions/{prescription.pk}/")
        self.assertContains(page, "Megamox 1 g")
        self.assertContains(page, self.patient.full_name)

    def test_post_op_instructions_are_chosen_for_the_surgery(self):
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/instructions/?surgery={self.surgery.pk}")
        chosen = [sheet.name_en for sheet in page.context["chosen"]]
        self.assertEqual(chosen, ["General instructions after surgery", "Extra instructions after sinus lift"])
        self.assertContains(page, self.patient.full_name)
        self.assertContains(page, "لا تنفّ أنفك")
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/instructions/?surgery={self.surgery.pk}&language=en")
        self.assertContains(page, "Do not blow your nose")

    def test_secretary_prints_instructions_but_does_not_prescribe(self):
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get(f"/prescriptions/patient/{self.patient.pk}/instructions/").status_code, 200)
        self.assertEqual(self.client.get(f"/prescriptions/patient/{self.patient.pk}/new/").status_code, 403)


class InjectionAndSheetTests(TestCase):
    def test_injections_are_offered_and_ticked_sheets_are_printed(self):
        from apps.core.testing import make_patient
        from apps.prescriptions.models import DrugGroup, InstructionSheet

        branch = setup_clinic()
        self.assertTrue(DrugGroup.objects.filter(kind=DrugGroup.Kind.INJECTION, name_en__contains="(IM").exists())
        patient = make_patient(branch)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        sinus = InstructionSheet.objects.exclude(procedures="").first()
        page = self.client.get(f"/prescriptions/patient/{patient.pk}/instructions/", {"sheet": [sinus.pk]})
        self.assertEqual([sheet for sheet, _lines in page.context["blocks"]], [sinus])
        self.assertContains(page, 'onchange="this.submit()"')


class Round16PapersTests(TestCase):
    """Round 16: the professional sick leave, the patient's consents (signed on the tablet or on paper), and the
    treatment plan printed with the prices and the specialists referred."""

    def setUp(self):
        from apps.prescriptions.defaults import load_defaults

        self.branch = setup_clinic()
        load_defaults()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        make_user("sec", "secretary")
        self.client.login(username="dentist", password=PASSWORD)

    def test_a_sick_leave_is_written_and_printed(self):
        from apps.prescriptions.models import SickLeave

        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/sick-leave/")
        self.assertEqual(page.context["form"].initial["dentist"], self.dentist)
        response = self.client.post(f"/prescriptions/patient/{self.patient.pk}/sick-leave/", {
            "dentist": self.dentist.pk, "seen_on": "11/10/2026", "diagnosis": "Impacted lower wisdom tooth",
            "treatment": "Surgical extraction of 38", "days": "3", "starts_on": "11/10/2026", "purpose": "work"})
        leave = SickLeave.objects.get()
        self.assertRedirects(response, leave.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(leave.ends_on.strftime("%d/%m/%Y"), "13/10/2026")
        paper = self.client.get(leave.get_absolute_url() + "?lang=en")
        self.assertContains(paper, "13/10/2026")
        self.assertContains(paper, "Impacted lower wisdom tooth")
        self.assertContains(self.client.get(leave.get_absolute_url()), "إجازة")  # the Arabic paper

    def test_the_consent_that_fits_the_plan_is_signed_on_the_tablet(self):
        from apps.charting.models import PlanItem, TreatmentPlan
        from apps.clinical.models import TreatmentStepType
        from apps.prescriptions.models import ConsentTemplate, PatientConsent

        plan = TreatmentPlan.objects.create(patient=self.patient)
        PlanItem.objects.create(plan=plan, step_type=TreatmentStepType.objects.get(name_en="Implant placement"),
                                teeth="36")
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/consent/")
        implant = ConsentTemplate.objects.get(name_en="Consent to dental implant surgery")
        self.assertEqual(page.context["form"].initial["template"], implant)
        self.client.post(f"/prescriptions/patient/{self.patient.pk}/consent/", {
            "template": implant.pk, "procedure": "Implant 36", "teeth": "36", "language": "ar"})
        consent = PatientConsent.objects.get()
        self.assertFalse(consent.is_signed)
        self.assertContains(self.client.get(consent.get_absolute_url()), "التدخين")
        png = "data:image/png;base64," + __import__("base64").b64encode(
            b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
        self.client.post(consent.get_absolute_url(), {"signature": png})
        consent.refresh_from_db()
        self.assertTrue(consent.is_signed)
        # The reception sees it in the file.
        self.client.login(username="sec", password=PASSWORD)
        self.assertContains(self.client.get(f"/patients/{self.patient.pk}/"), "Implant 36")

    def test_the_plan_prints_the_usual_prices_and_the_referrals(self):
        from apps.billing.models import Service
        from apps.charting.models import PlanItem, TreatmentPlan
        from apps.clinical.models import TreatmentStepType
        from apps.specialties.models import Referral

        crown = TreatmentStepType.objects.get(name_en="Implant placement")
        service = Service.objects.create(name_ar="زرعة", name_en="Implant", price=Decimal("9000"))
        crown.service = service
        crown.save()
        plan = TreatmentPlan.objects.create(patient=self.patient, dentist=self.dentist)
        PlanItem.objects.create(plan=plan, step_type=crown, teeth="36 46")
        endo = make_dentist("endo", kind="specialist")
        Referral.objects.create(branch=self.branch, patient=self.patient, from_dentist=self.dentist,
                                to_dentist=endo, reason="Root canal 26", teeth="26")
        page = self.client.get(f"/chart/plan/{plan.pk}/print/?lang=en")
        self.assertEqual(page.context["total"], Decimal("18000"))
        self.assertContains(page, "usual price")
        self.assertContains(page, "Root canal 26")
        self.assertIsNone(self.client.get(f"/chart/plan/{plan.pk}/print/?prices=0").context["total"])
        # The reception prints it too when the owner lets it see the plans.
        from apps.core.models import ClinicSettings

        options = ClinicSettings.get()
        options.reception_sees = ["plan"]
        options.save()
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get(f"/chart/plan/{plan.pk}/print/").status_code, 200)
