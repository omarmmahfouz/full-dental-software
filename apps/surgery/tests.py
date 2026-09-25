from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.charting.models import PlanItem, ToothState, TreatmentPlan
from apps.clinical.models import TreatmentStepType
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.surgery.models import ImplantSystem, SavedSearch, Surgery, SurgerySite

SITE_FIELDS = ["tooth", "extraction", "flap", "simple_implant", "immediate_implant", "expansion", "splitting",
               "closed_sinus", "open_sinus", "gbr", "guided", "implant_system", "implant_diameter", "implant_length",
               "lot_number", "insertion_torque", "isq", "notes"]


def surgery_data(patient, operator, sites, **extra):
    data = {
        "patient_lookup": patient.file_number, "date": timezone.localdate().isoformat(), "difficulty": "simple",
        "operator_1": operator.pk, "exposure": "unknown", "update_chart": "on",
        "sites-TOTAL_FORMS": len(sites), "sites-INITIAL_FORMS": 0, "sites-MIN_NUM_FORMS": 0, "sites-MAX_NUM_FORMS": 1000,
    }
    for index, site in enumerate(sites):
        for name in SITE_FIELDS:
            value = site.get(name, "")
            if value is True:
                value = "on"
            if value not in ("", False):
                data[f"sites-{index}-{name}"] = value
    data.update(extra)
    return data


class SurgeryTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="candidate")
        self.partner = make_dentist("dentist2", kind="candidate")
        self.outsider = make_dentist("dentist3", kind="candidate")
        self.instructor = make_dentist("instructor", kind="supervisor")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.system = ImplantSystem.objects.get(company="Osstem")
        ToothState.objects.create(patient=self.patient, tooth=46, hopeless=True)
        ToothState.objects.create(patient=self.patient, tooth=36, status=ToothState.Status.MISSING)
        self.client.login(username="dentist", password=PASSWORD)

    def implant(self, tooth, **extra):
        site = {"tooth": tooth, "flap": True, "simple_implant": True, "implant_system": self.system.pk,
                "implant_diameter": "4.5", "implant_length": "10", "insertion_torque": 35}
        site.update(extra)
        return site

    def test_surgery_updates_chart_plan_and_counts_for_the_candidate(self):
        plan = TreatmentPlan.objects.create(patient=self.patient, status=TreatmentPlan.Status.APPROVED)
        placement = PlanItem.objects.create(plan=plan, step_type=TreatmentStepType.objects.get(name_en="Implant placement"),
                                            teeth="36")
        sinus = PlanItem.objects.create(plan=plan, step_type=TreatmentStepType.objects.get(name_en="Closed sinus lift"),
                                        teeth="16")
        response = self.client.post("/surgery/new/", surgery_data(
            self.patient, self.dentist,
            [self.implant(36), self.implant(46, extraction=True, flap=False, simple_implant=False, immediate_implant=True)],
            operator_2=self.partner.pk, instructor=self.instructor.pk,
        ))
        surgery = Surgery.objects.get()
        self.assertRedirects(response, surgery.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(surgery.number, f"SUR-{surgery.pk:05d}")
        self.assertTrue(surgery.chart_updated)
        for tooth in (36, 46):
            state = ToothState.objects.get(patient=self.patient, tooth=tooth)
            self.assertEqual(state.status, ToothState.Status.IMPLANT)
            self.assertEqual(state.implant_site.implant_status, SurgerySite.ImplantStatus.PLACED)
        placement.refresh_from_db()
        sinus.refresh_from_db()
        self.assertEqual((placement.status, placement.done_surgery), (PlanItem.Status.DONE, surgery))
        self.assertEqual(sinus.status, PlanItem.Status.PLANNED)

        # Portfolio: 2 implants as operator 1 against the course requirement.
        page = self.client.get(f"/dentists/{self.dentist.pk}/")
        self.assertEqual(page.context["placed"], 2)
        self.assertEqual(page.context["counts"]["op1"], 1)
        # The patient becomes visible to operator 2.
        self.client.login(username="dentist2", password=PASSWORD)
        self.assertEqual(self.client.get(self.patient.get_absolute_url()).status_code, 200)

    def test_site_validation(self):
        no_details = self.implant(36, implant_system="", implant_diameter="")
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [no_details]))
        self.assertIn("implant_system", response.context["formset"].forms[0].errors)
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [self.implant(36), self.implant(36)]))
        self.assertIn("tooth", response.context["formset"].forms[1].errors)
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [{"tooth": 36}]))
        self.assertIn("tooth", response.context["formset"].forms[0].errors)  # no procedure ticked
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [self.implant(36)],
                                                                  operator_2=self.dentist.pk))
        self.assertTrue(response.context["form"].non_field_errors())  # same dentist twice
        self.assertFalse(Surgery.objects.exists())

    def test_only_the_team_or_management_can_edit(self):
        surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.partner,
                                         instructor=self.instructor)
        make_user("sup", "supervisor")
        self.assertEqual(self.client.get(f"/surgery/{surgery.pk}/edit/").status_code, 403)  # not on the team
        self.client.login(username="instructor", password=PASSWORD)
        self.assertEqual(self.client.get(f"/surgery/{surgery.pk}/edit/").status_code, 200)
        self.client.login(username="sup", password=PASSWORD)
        self.assertEqual(self.client.get(f"/surgery/{surgery.pk}/edit/").status_code, 200)
        self.client.login(username="dentist3", password=PASSWORD)
        self.assertEqual(self.client.get(f"/surgery/{surgery.pk}/").status_code, 200)  # every CIA dentist can read it

    def test_marking_an_implant_failed_updates_the_chart(self):
        self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [self.implant(36)]))
        site = SurgerySite.objects.get()
        self.client.post(f"/surgery/implant/{site.pk}/", {"implant_status": "failed", "failed_on": "2026-09-01",
                                                          "failure_reason": "no osseointegration"})
        site.refresh_from_db()
        self.assertEqual(site.implant_status, SurgerySite.ImplantStatus.FAILED)
        self.assertEqual(ToothState.objects.get(patient=self.patient, tooth=36).status, ToothState.Status.MISSING)
        self.assertEqual(self.client.get(f"/surgery/{site.surgery_id}/?print=1").status_code, 200)


class FinderTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.supervisor = make_user("sup", "supervisor")
        self.dentist = make_dentist("dentist", kind="candidate")
        man = make_patient(self.branch, nid="29001150101234", phone="01001234567")  # male
        woman = make_patient(self.branch, nid="30105220101242", phone="01112223334")  # female
        osstem = ImplantSystem.objects.get(company="Osstem")
        mis = ImplantSystem.objects.get(company="MIS")
        old = timezone.localdate() - timedelta(days=200)

        def site(patient, tooth, system, status, **extra):
            surgery = Surgery.objects.create(branch=self.branch, patient=patient, operator_1=self.dentist, date=old)
            obj = SurgerySite.objects.create(surgery=surgery, tooth=tooth, simple_implant=True, implant_system=system,
                                             implant_diameter=Decimal("4.5"), implant_length=Decimal("10"),
                                             insertion_torque=40, **extra)
            SurgerySite.objects.filter(pk=obj.pk).update(
                implant_status=status, loaded_on=old + timedelta(days=100) if status == "loaded" else None)
            return obj

        site(man, 36, osstem, "loaded")
        site(man, 46, osstem, "failed")
        site(woman, 26, mis, "loaded", open_sinus=True)
        site(woman, 16, mis, "placed", gbr=True)
        surgery = Surgery.objects.create(branch=self.branch, patient=woman, operator_1=self.dentist, date=old)
        SurgerySite.objects.create(surgery=surgery, tooth=38, extraction=True)  # a site without implant

    def find(self, **params):
        self.client.login(username="sup", password=PASSWORD)
        return self.client.get("/surgery/finder/", params)

    def test_management_only(self):
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/surgery/finder/").status_code, 403)
        self.assertEqual(self.find().status_code, 200)

    def test_filters(self):
        self.assertEqual(self.find().context["overall"]["implants"], 4)
        self.assertEqual(self.find(result="sites").context["overall"]["sites"], 5)
        self.assertEqual(self.find(status="placed").context["overall"]["implants"], 1)  # waiting for 2nd stage
        self.assertEqual(self.find(company="MIS").context["overall"]["implants"], 2)
        self.assertEqual(self.find(gender="F").context["overall"]["implants"], 2)
        self.assertEqual(self.find(procedures_any=["open_sinus", "gbr"]).context["overall"]["implants"], 2)
        self.assertEqual(self.find(jaw="upper").context["overall"]["implants"], 2)
        self.assertEqual(self.find(tooth_type="molar", operator=self.dentist.pk).context["overall"]["implants"], 4)

    def test_statistics_by_company(self):
        response = self.find(group_by="company")
        self.assertEqual(response.context["overall"]["survival"], 75.0)
        self.assertEqual(response.context["overall"]["days_to_loading"], 100)
        groups = {g["key"]: g for g in response.context["groups"]}
        self.assertEqual((groups["Osstem"]["implants"], groups["Osstem"]["survival"]), (2, 50.0))
        self.assertEqual(groups["MIS"]["survival"], 100.0)

    def test_csv_export_and_saved_search(self):
        response = self.find(company="Osstem", export="csv")
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        content = response.content.decode("utf-8")
        self.assertTrue(content.startswith("﻿"))  # opens correctly in Excel
        self.assertEqual(len(content.strip().splitlines()), 3)  # header + 2 implants
        self.client.post("/surgery/finder/save/", {"name": "Osstem cases", "query": "company=Osstem", "shared": "on"})
        self.assertEqual(SavedSearch.objects.get().owner, self.supervisor)
        self.assertContains(self.find(), "Osstem cases")
