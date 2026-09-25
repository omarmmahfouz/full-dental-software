import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone, translation

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
        translation.activate("en")  # change summaries are written in the language of whoever records them
        self.addCleanup(translation.deactivate)
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
        self.login("sec")  # the reception reads the plan and treatments on the patient file instead
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(f"{self.url}tooth/36/").status_code, 403)
        self.login("dentist2")  # CIA dentists see every patient
        self.assertEqual(self.client.get(self.url).status_code, 200)
        make_user("stock", "stock")
        self.login("stock")
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

    def test_plan_has_implant_and_restorative_parts(self):
        implant = TreatmentStepType.objects.get(name_en="Implant placement")
        composite = TreatmentStepType.objects.get(name_en="Composite restoration")
        self.assertEqual(implant.category, TreatmentStepType.Category.IMPLANT)
        self.assertEqual(TreatmentStepType.objects.get(name_en="Sinus lift").category, TreatmentStepType.Category.IMPLANT)
        self.assertEqual(composite.category, TreatmentStepType.Category.RESTORATIVE)
        self.login("dentist")
        page = self.client.get(f"{self.url}plan/new/")
        implant_part, restorative_part = page.context["sections"]
        self.assertEqual(implant_part["code"], "implant")
        self.assertEqual(implant_part["forms"][0]["phase"].value(), PlanItem.Phase.SURGICAL)  # new rows start surgical
        self.assertContains(page, f'value="{implant.pk}" data-category="implant"')
        self.assertContains(page, 'data-teeth-missing="36"')  # the tooth picker marks the chart's missing teeth
        self.assertContains(page, 'data-teeth-picker="multi"')
        self.client.post(f"{self.url}plan/new/", {
            "title": "Plan B", "dentist": self.dentist.pk,
            "items-TOTAL_FORMS": 3, "items-INITIAL_FORMS": 0, "items-MIN_NUM_FORMS": 0, "items-MAX_NUM_FORMS": 1000,
            "items-0-phase": 3, "items-0-step_type": implant.pk, "items-0-teeth": "46 36 16",  # same implant, 3 teeth
            "items-1-phase": 2, "items-1-step_type": composite.pk, "items-1-teeth": "25",
            "items-2-phase": 3, "items-2-step_type": "", "items-2-teeth": "",  # empty implant row: not an item
        })
        plan = TreatmentPlan.objects.get()
        self.assertEqual(plan.items.count(), 2)
        self.assertEqual(plan.items.get(step_type=implant).teeth, "16, 46, 36")
        sections = plan.sections()
        self.assertEqual([(s["code"], len(s["items"])) for s in sections], [("implant", 1), ("restorative", 1)])
        edit = self.client.get(f"/chart/plan/{plan.pk}/edit/")
        self.assertEqual([len([f for f in s["forms"] if f.instance.pk]) for s in edit.context["sections"]], [1, 1])
        self.assertContains(self.client.get(f"/chart/plan/{plan.pk}/"), "Restorative and other")

    def test_case_report_and_photos_pages(self):
        self.login("dentist")
        self.assertEqual(self.client.get(f"{self.url}case-report/").status_code, 200)
        anonymous = self.client.get(f"{self.url}case-report/?anonymous=1")
        self.assertNotContains(anonymous, self.patient.full_name)
        self.assertEqual(self.client.get(f"{self.url}photos/").status_code, 200)


class ReceptionSyncTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        make_user("sec", "secretary")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)

    def test_missing_teeth_follow_the_chart(self):
        from apps.patients.models import MissingTeeth

        self.client.login(username="dentist", password=PASSWORD)
        self.client.post(f"/chart/patient/{self.patient.pk}/tooth/36/", {"status": "missing", "mobility": 0})
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.missing_teeth, self.patient.missing_teeth_notes), (MissingTeeth.SINGLE, "36"))
        for tooth in (11, 12, 13, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26, 27):
            ToothState.objects.create(patient=self.patient, tooth=tooth, status=ToothState.Status.MISSING)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.missing_teeth, MissingTeeth.FULL_ARCH)
        self.client.login(username="sec", password=PASSWORD)
        self.assertContains(self.client.get(f"/patients/{self.patient.pk}/"), "الضرس الأول السفلي الأيسر")

    def test_the_dentists_medical_history_reaches_the_reception(self):
        from apps.patients.models import MedicalCondition

        diabetes = MedicalCondition.objects.get(name_en="Diabetes")
        smoker = MedicalCondition.objects.get(name_en="Smoker")
        self.patient.medical_conditions.set([smoker])  # what the patient told the secretary
        self.client.login(username="dentist", password=PASSWORD)
        form = self.client.get(f"/chart/patient/{self.patient.pk}/exam/new/").context["form"]
        self.assertEqual(list(form.initial["conditions"]), [smoker])
        exam = Examination.objects.create(patient=self.patient, allergy_penicillin=True)
        response = self.client.post(f"/chart/exam/{exam.pk}/edit/", {
            "exam_date": timezone.localdate().strftime("%d/%m/%Y"), "conditions": [diabetes.pk, smoker.pk],
            "allergy_penicillin": "on",
        })
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.assertEqual(set(self.patient.medical_conditions.all()), {diabetes, smoker})
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get(f"/patients/{self.patient.pk}/")
        self.assertContains(page, "بنسلين")


class ReceptionHistoryTests(TestCase):
    def test_the_reception_asks_the_chart_questions_and_the_dentist_starts_from_them(self):
        from apps.patients.models import MedicalCondition

        branch = setup_clinic()
        patient = make_patient(branch)
        make_dentist("dentist", kind="fulltime")
        make_user("sec", "secretary")
        diabetes = MedicalCondition.objects.get(name_en="Diabetes")
        self.client.login(username="sec", password=PASSWORD)
        form = self.client.get(f"/patients/{patient.pk}/history/").context["form"]
        self.assertIn("bp_last_systolic", form.fields)
        self.assertNotIn("cooperation_score", form.fields)
        self.client.post(f"/patients/{patient.pk}/history/", {
            "conditions": [diabetes.pk], "bp_last_systolic": "150", "bp_last_diastolic": "95", "smoker": "on",
            "cigarettes_per_day": "20", "allergy_penicillin": "on"})
        history = Examination.objects.get()
        self.assertTrue(history.history_only)
        self.assertEqual(list(patient.medical_conditions.all()), [diabetes])
        page = self.client.get(f"/patients/{patient.pk}/")
        self.assertContains(page, "150/95")
        # Asked again: the same record is updated, not a second one.
        self.client.post(f"/patients/{patient.pk}/history/", {"conditions": [diabetes.pk], "bp_last_systolic": "140"})
        self.assertEqual(Examination.objects.count(), 1)
        self.client.login(username="dentist", password=PASSWORD)
        initial = self.client.get(f"/chart/patient/{patient.pk}/exam/new/").context["form"].initial
        self.assertEqual(initial["bp_last_systolic"], 140)


class PhotoFolderAndLogBookTests(TestCase):
    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings

        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=self.media)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="candidate")
        make_user("sec", "secretary")
        self.patient = make_patient(self.branch, name="Test Patient", assigned_dentist=self.dentist)

    def photo(self, **extra):
        from django.core.files.base import ContentFile

        from apps.charting.models import ClinicalPhoto, PhotoType

        shot = PhotoType.objects.get(stage="surgery", name_en="Implant placed with cover screw")
        data = {"stage": "surgery", "photo_type": shot, "teeth": "36, 46", "taken_on": timezone.localdate()}
        data.update(extra)
        return ClinicalPhoto.objects.create(patient=self.patient, file=ContentFile(b"jpeg", name="IMG_0001.JPG"), **data)

    def test_photos_are_saved_in_readable_folders_and_zipped(self):
        import io
        import zipfile

        photo = self.photo()
        day = timezone.localdate().strftime("%d-%m-%Y")
        self.assertEqual(photo.file.name, f"Patient photos/{self.patient.file_number} Test Patient/2 Surgery photos/"
                                          f"Implant_placed_with_cover_screw_36-46_{day}.jpg")
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get(photo.file.url).status_code, 200)
        response = self.client.get(f"/chart/patient/{self.patient.pk}/photos/zip/")
        names = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))).namelist()
        self.assertEqual(names, [f"{self.patient.file_number} Test Patient/2 Surgery photos/"
                                 f"Implant placed with cover screw 36-46 {day}.jpg"])
        self.client.login(username="sec", password=PASSWORD)  # clinical photos are for the dentists
        self.assertEqual(self.client.get(photo.file.url).status_code, 403)

    def test_old_photos_are_moved_into_the_folders(self):
        import os

        from django.core.management import call_command

        photo = self.photo()
        old = f"patients/{self.patient.pk}/photos/surgery/0a1b2c.jpg"
        os.makedirs(os.path.join(self.media, os.path.dirname(old)))
        os.replace(photo.file.path, os.path.join(self.media, old))
        type(photo).objects.filter(pk=photo.pk).update(file=old)
        call_command("organize_photos", stdout=io.StringIO())
        photo.refresh_from_db()
        self.assertTrue(photo.file.name.startswith("Patient photos/"))
        self.assertTrue(os.path.exists(photo.file.path))
        self.assertFalse(os.path.exists(os.path.join(self.media, old)))

    def test_log_book_pages_have_fixed_frames_and_the_procedure(self):
        surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.dentist)
        SurgerySite.objects.create(surgery=surgery, tooth=36, simple_implant=True, gbr=True,
                                   implant_system=ImplantSystem.objects.first(), implant_diameter=Decimal("4.3"),
                                   implant_length=Decimal("10"))
        self.photo(surgery=surgery)
        self.photo(stage="diagnostic", photo_type=None, notes="Panoramic", teeth="")
        self.client.login(username="dentist", password=PASSWORD)
        page = self.client.get(f"/chart/patient/{self.patient.pk}/photos/logbook/?per_row=3&stage=surgery")
        self.assertEqual([p["code"] for p in page.context["pages"]], ["surgery"])
        self.assertContains(page, "--frame-w: 56mm")
        self.assertIn("36: Simple implant, GBR", page.context["pages"][0]["description"])
        self.assertContains(page, "Implant placed with cover screw")
