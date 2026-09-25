from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.charting.models import Examination, PlanItem, ToothChange, ToothState, TreatmentPlan
from apps.charting.rules import apply_changes, exam_changes, plan_changes
from apps.charting.teeth import parse_surfaces, parse_teeth
from apps.clinical.models import ChartEffect, TreatmentStepType
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.surgery.models import ImplantSystem, Surgery, SurgerySite


class TeethParsingTests(TestCase):
    def test_numbers_ranges_and_arabic_digits(self):
        self.assertEqual(parse_teeth("11-13, 21"), [13, 12, 11, 21])
        self.assertEqual(parse_teeth("13-23"), [13, 12, 11, 21, 22, 23])  # across the midline
        self.assertEqual(parse_teeth("٣٦ 46"), [46, 36])
        self.assertEqual(parse_teeth(""), [])
        with self.assertRaises(ValidationError):
            parse_teeth("19")

    def test_surfaces(self):
        self.assertEqual(parse_surfaces("dom"), "MOD")
        self.assertEqual(parse_surfaces("IF"), "OB")  # incisal -> occlusal, facial -> buccal
        with self.assertRaises(ValidationError):
            parse_surfaces("X")


class ChartRulesTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.user = make_user("sup", "supervisor")
        self.dentist = make_dentist("dentist", kind="candidate")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)

    def apply(self, effect, teeth, surfaces="", material=""):
        changes = plan_changes(self.patient, effect, teeth, surfaces, material)
        apply_changes(self.patient, changes, self.user, ToothChange.Source.TREATMENT)
        return changes

    def state(self, tooth):
        return ToothState.objects.get(patient=self.patient, tooth=tooth)

    def implant(self, tooth, status=SurgerySite.ImplantStatus.PLACED):
        surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.dentist)
        site = SurgerySite.objects.create(surgery=surgery, tooth=tooth, simple_implant=True,
                                          implant_system=ImplantSystem.objects.first(),
                                          implant_diameter=Decimal("4.5"), implant_length=Decimal("10"))
        SurgerySite.objects.filter(pk=site.pk).update(implant_status=status)
        site.refresh_from_db()
        self.apply_sites(tooth, site)
        return site

    def apply_sites(self, tooth, site):
        changes = plan_changes(self.patient, ChartEffect.IMPLANT, [tooth], sites={tooth: site})
        apply_changes(self.patient, changes, self.user, ToothChange.Source.SURGERY)

    def test_caries_restored_becomes_filled(self):
        ToothState.objects.create(patient=self.patient, tooth=12, caries=True, caries_surfaces="MO")
        changes = self.apply(ChartEffect.FILLING, [12], "MO", "composite")
        self.assertIn("filled composite (MO)", changes[0].summary)
        state = self.state(12)
        self.assertEqual((state.caries, state.filled, state.filling_surfaces, state.filling_material),
                         (False, True, "MO", "composite"))
        change = ToothChange.objects.get()
        self.assertEqual((change.before["caries"], change.after["filled"]), (True, True))

    def test_partial_restoration_keeps_the_rest_of_the_caries(self):
        ToothState.objects.create(patient=self.patient, tooth=36, caries=True, caries_surfaces="MOD")
        self.apply(ChartEffect.FILLING, [36], "MO", "composite")
        state = self.state(36)
        self.assertEqual((state.caries, state.caries_surfaces, state.filling_surfaces), (True, "D", "MO"))

    def test_extraction_rct_and_crown(self):
        self.apply(ChartEffect.EXTRACTION, [18])
        self.assertEqual(self.state(18).status, ToothState.Status.MISSING)
        self.apply(ChartEffect.RCT, [21])
        self.apply(ChartEffect.CROWN, [21], material="zirconia")
        state = self.state(21)
        self.assertEqual((state.rct, state.crown, state.crown_material), (True, True, "zirconia"))

    def test_nothing_to_change_gives_no_change(self):
        self.apply(ChartEffect.EXTRACTION, [18])
        self.assertEqual(plan_changes(self.patient, ChartEffect.EXTRACTION, [18]), [])
        self.assertEqual(plan_changes(self.patient, ChartEffect.NONE, [11]), [])

    def test_implant_life_follows_the_treatments(self):
        site = self.implant(46)
        self.assertEqual((self.state(46).status, self.state(46).implant_site), (ToothState.Status.IMPLANT, site))
        self.apply(ChartEffect.UNCOVER, [46])
        site.refresh_from_db()
        self.assertEqual(site.implant_status, SurgerySite.ImplantStatus.UNCOVERED)
        self.assertIsNotNone(site.uncovered_on)
        self.apply(ChartEffect.DELIVERY, [46])
        site.refresh_from_db()
        self.assertEqual(site.implant_status, SurgerySite.ImplantStatus.LOADED)
        # Never backwards: an impression after loading does not move the stage.
        self.assertEqual(plan_changes(self.patient, ChartEffect.IMPRESSION, [46]), [])

    def test_failed_implant_makes_the_tooth_missing(self):
        site = self.implant(46, SurgerySite.ImplantStatus.LOADED)
        changes = self.apply(ChartEffect.IMPLANT_FAILED, [46])
        self.assertIn("missing", changes[0].summary)
        site.refresh_from_db()
        state = self.state(46)
        self.assertEqual((state.status, state.implant_site), (ToothState.Status.MISSING, None))
        self.assertEqual(site.implant_status, SurgerySite.ImplantStatus.FAILED)
        self.assertIsNotNone(site.failed_on)

    def test_examination_tooth_lists_fill_the_chart(self):
        exam = Examination.objects.create(patient=self.patient, teeth_missing="36, 46", teeth_carious="25",
                                          teeth_filled="16", teeth_hopeless="17", teeth_mobility="31")
        changes = exam_changes(self.patient, exam)
        self.assertEqual(sorted(c.tooth for c in changes), [16, 17, 25, 31, 36, 46])
        apply_changes(self.patient, changes, self.user, ToothChange.Source.EXAM, examination=exam)
        self.assertEqual(self.state(36).status, ToothState.Status.MISSING)
        self.assertTrue(self.state(25).caries)
        self.assertTrue(self.state(16).filled)
        self.assertTrue(self.state(17).hopeless)
        self.assertEqual(self.state(31).mobility, 1)
        self.assertEqual(exam_changes(self.patient, exam), [])  # applying twice changes nothing


class ChartPageTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="candidate")
        self.other = make_dentist("dentist2", kind="candidate")
        self.secretary = make_user("sec", "secretary")
        self.supervisor_user = make_user("sup", "supervisor")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        ToothState.objects.create(patient=self.patient, tooth=36, status=ToothState.Status.MISSING)
        self.url = f"/chart/patient/{self.patient.pk}/"

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)

    def test_who_can_see_and_edit_the_chart(self):
        self.login("dentist")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("<svg", response.context["svg"])
        self.assertTrue(response.context["can_edit"])
        self.login("sec")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit"])
        self.assertEqual(self.client.get(f"{self.url}tooth/36/").status_code, 403)
        self.login("dentist2")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_manual_tooth_edit_is_logged(self):
        self.login("dentist")
        self.client.post(f"{self.url}tooth/11/", {"status": "present", "caries": "on", "caries_surfaces": ["M"],
                                                  "mobility": 0})
        state = ToothState.objects.get(patient=self.patient, tooth=11)
        self.assertEqual((state.caries, state.caries_surfaces), (True, "M"))
        change = ToothChange.objects.get(tooth=11)
        self.assertEqual((change.source, change.changed_by), (ToothChange.Source.MANUAL, self.dentist.user))

    def test_preview_lists_changes_before_saving(self):
        ToothState.objects.create(patient=self.patient, tooth=12, caries=True, caries_surfaces="MO")
        composite = TreatmentStepType.objects.get(name_en="Composite restoration")
        self.login("dentist")
        data = self.client.get("/chart/preview/", {"patient": self.patient.pk, "step_type": composite.pk,
                                                   "teeth": "12", "surfaces": "mo"}).json()
        self.assertEqual(data["changes"][0]["tooth"], 12)
        self.assertIn("filled composite (MO)", data["changes"][0]["summary"])
        data = self.client.get("/chart/preview/", {"lookup": self.patient.file_number, "step_type": composite.pk,
                                                   "teeth": "19"}).json()
        self.assertIn("error", data)
        self.assertFalse(ToothState.objects.get(patient=self.patient, tooth=12).filled)  # preview saves nothing

    def test_examination_form_updates_chart(self):
        self.login("dentist")
        response = self.client.post(f"{self.url}exam/new/", {
            "exam_date": "2026-09-01", "examined_by": self.dentist.pk, "teeth_missing": "46", "teeth_carious": "25",
            "update_chart": "on",
        })
        exam = Examination.objects.get()
        self.assertRedirects(response, f"/chart/exam/{exam.pk}/", fetch_redirect_response=False)
        self.assertEqual(ToothState.objects.get(patient=self.patient, tooth=46).status, ToothState.Status.MISSING)
        self.assertTrue(ToothChange.objects.filter(examination=exam, tooth=25).exists())
        self.assertEqual(self.client.get(f"/chart/exam/{exam.pk}/").status_code, 200)

    def test_treatment_plan_is_approved_by_management_only(self):
        implant = TreatmentStepType.objects.get(name_en="Implant placement")
        self.login("dentist")
        self.client.post(f"{self.url}plan/new/", {
            "title": "Plan A", "dentist": self.dentist.pk,
            "items-TOTAL_FORMS": 2, "items-INITIAL_FORMS": 0, "items-MIN_NUM_FORMS": 0, "items-MAX_NUM_FORMS": 1000,
            "items-0-phase": 3, "items-0-step_type": implant.pk, "items-0-teeth": "36",
            "items-1-phase": 2, "items-1-step_type": "", "items-1-teeth": "",  # untouched extra row
        })
        plan = TreatmentPlan.objects.get()
        self.assertEqual((plan.status, plan.items.count()), (TreatmentPlan.Status.PROPOSED, 1))
        chart = self.client.get(self.url)
        self.assertIn("36", chart.context["svg"])
        self.assertEqual(self.client.post(f"/chart/plan/{plan.pk}/action/", {"action": "approve"}).status_code, 403)
        self.login("sup")
        self.client.post(f"/chart/plan/{plan.pk}/action/", {"action": "approve"})
        plan.refresh_from_db()
        self.assertEqual(plan.status, TreatmentPlan.Status.APPROVED)
        item = plan.items.get()
        self.client.post(f"/chart/plan/{plan.pk}/action/", {"action": "item_cancel", "item": item.pk})
        item.refresh_from_db()
        self.assertEqual(item.status, PlanItem.Status.CANCELLED)

    def test_case_report_and_photos_pages(self):
        self.login("dentist")
        self.assertEqual(self.client.get(f"{self.url}case-report/").status_code, 200)
        anonymous = self.client.get(f"{self.url}case-report/?anonymous=1")
        self.assertNotContains(anonymous, self.patient.full_name)
        self.assertEqual(self.client.get(f"{self.url}photos/").status_code, 200)
