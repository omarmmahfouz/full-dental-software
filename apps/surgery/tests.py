from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.charting.models import PlanItem, ToothState, TreatmentPlan
from apps.clinical.models import TreatmentStepType
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.surgery.models import ImplantSystem, SavedSearch, Surgery, SurgerySite

SITE_FIELDS = ["id", "tooth", "operator", "extraction", "flap", "simple_implant", "immediate_implant", "expansion", "splitting",
               "closed_sinus", "open_sinus", "gbr", "guided", "implant_system", "implant_diameter", "implant_length",
               "lot_number", "stock_choice", "insertion_torque", "isq", "notes"]


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


class OperatorTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.first = make_dentist("dentist", kind="candidate")
        self.second = make_dentist("dentist2", kind="candidate")
        self.head = make_user("head", "head_cia")
        self.patient = make_patient(self.branch, assigned_dentist=self.first)
        self.system = ImplantSystem.objects.get(company="Osstem")

    def implant(self, tooth, **extra):
        site = {"tooth": tooth, "simple_implant": True, "implant_system": self.system.pk, "implant_diameter": "4",
                "implant_length": "10"}
        site.update(extra)
        return site

    def test_operator_2_works_on_other_teeth_and_gets_them_counted(self):
        self.client.login(username="dentist", password=PASSWORD)
        response = self.client.post("/surgery/new/", surgery_data(
            self.patient, self.first, [self.implant(36), self.implant(46, operator=self.second.pk)],
            operator_2=self.second.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SurgerySite.objects.done_by(self.first).get().tooth, 36)
        self.assertEqual(SurgerySite.objects.done_by(self.second).get().tooth, 46)
        # the operator of a tooth must be one of the two operators
        outsider = make_dentist("dentist3", kind="candidate", login=False)
        response = self.client.post("/surgery/new/", surgery_data(
            self.patient, self.first, [self.implant(26, operator=outsider.pk)]))
        self.assertEqual(response.status_code, 200)

    def test_changing_the_operator_after_saving_needs_approval(self):
        from apps.core.models import ChangeRequest

        surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.first,
                                         created_by=self.first.user)
        site = SurgerySite.objects.create(surgery=surgery, tooth=36, simple_implant=True, implant_system=self.system,
                                          implant_diameter=Decimal("4"), implant_length=Decimal("10"))
        self.client.login(username="dentist", password=PASSWORD)
        data = surgery_data(self.patient, self.second, [self.implant(36, id=site.pk)], **{"sites-INITIAL_FORMS": 1})
        self.client.post(f"/surgery/{surgery.pk}/edit/", data)
        surgery.refresh_from_db()
        self.assertEqual(surgery.operator_1, self.first)  # unchanged until approved
        change = ChangeRequest.objects.get(kind="operator")
        self.client.login(username="head", password=PASSWORD)
        self.client.post(f"/approvals/{change.pk}/", {"action": "approve"})
        surgery.refresh_from_db()
        self.assertEqual(surgery.operator_1, self.second)

    def test_treatment_operator_change_goes_to_approval(self):
        from apps.clinical.models import TreatmentStep
        from apps.core.models import ChangeRequest

        step = TreatmentStep.objects.create(patient=self.patient, operator=self.first,
                                            step_type=TreatmentStepType.objects.get(name_en="Scaling"))
        self.client.login(username="dentist", password=PASSWORD)
        self.client.post(f"/clinical/steps/{step.pk}/operator/", {"operator": self.second.pk})
        step.refresh_from_db()
        self.assertEqual(step.operator, self.first)
        self.assertEqual(ChangeRequest.objects.get().changes[0]["field"], "operator")
        self.client.login(username="head", password=PASSWORD)
        self.client.post(f"/clinical/steps/{step.pk}/operator/", {"operator": self.second.pk})
        step.refresh_from_db()
        self.assertEqual(step.operator, self.second)  # the head of CIA changes it directly


class ImplantStockTests(TestCase):
    """Choose the company, then the implant in stock by lot; saving the chart takes it out of stock."""

    def setUp(self):
        from apps.stock.models import StockCategory, StockItem, StockMovement
        from apps.stock.services import record_movement

        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="candidate")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.system = ImplantSystem.objects.get(company="Osstem")
        self.item = StockItem.objects.create(
            name="Osstem TS III 4.0 x 10", category=StockCategory.objects.get(name_en="Implants & components"),
            unit="piece", implant_system=self.system, implant_diameter=Decimal("4"), implant_length=Decimal("10"))
        record_movement(self.item, StockMovement.Kind.IN, 2, lot="LOT-A", expiry_date=timezone.localdate() + timedelta(days=400))
        record_movement(self.item, StockMovement.Kind.IN, 1, lot="LOT-B")
        self.client.login(username="dentist", password=PASSWORD)

    def implant(self, tooth, lot, **extra):
        site = {"tooth": tooth, "simple_implant": True, "implant_system": self.system.pk, "implant_diameter": "4",
                "implant_length": "10", "stock_choice": f"{self.item.pk}|{lot}"}
        site.update(extra)
        return site

    def left(self, lot):
        return {row["lot"]: row["left"] for row in self.item.lots()}.get(lot, 0)

    def test_lots_listed_by_company(self):
        response = self.client.get("/surgery/implant-lots/", {"system": self.system.pk})
        labels = [row["label"] for row in response.json()["lots"]]
        self.assertEqual(len(labels), 2)
        self.assertIn("LOT-A", labels[0])  # the lot that expires first comes first
        self.assertIn("2", labels[0])

    def test_saving_the_chart_takes_the_implant_out_and_gives_it_back(self):
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist,
                                                                  [self.implant(36, "LOT-A"), self.implant(46, "LOT-B")]))
        self.assertEqual(response.status_code, 302)
        surgery = Surgery.objects.get()
        site = surgery.sites.get(tooth=36)
        self.assertEqual((site.lot_number, site.implant_stock_item), ("LOT-A", self.item))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("1"))
        self.assertEqual((self.left("LOT-A"), self.left("LOT-B")), (1, 0))
        self.assertIn(surgery.number, site.stock_movement.destination)
        # Saving again changes nothing; changing the lot puts the first one back.
        other = surgery.sites.get(tooth=46)
        data = surgery_data(self.patient, self.dentist, [self.implant(36, "LOT-A", id=site.pk),
                                                         self.implant(46, "LOT-A", id=other.pk)],
                            **{"sites-INITIAL_FORMS": 2})
        self.client.post(f"/surgery/{surgery.pk}/edit/", data)
        self.assertEqual((self.left("LOT-A"), self.left("LOT-B")), (0, 1))
        # Removing a tooth gives its implant back.
        data = surgery_data(self.patient, self.dentist, [self.implant(36, "LOT-A", id=site.pk),
                                                         self.implant(46, "LOT-A", id=other.pk, DELETE="on")],
                            **{"sites-INITIAL_FORMS": 2})
        data["sites-1-DELETE"] = "on"
        self.client.post(f"/surgery/{surgery.pk}/edit/", data)
        self.assertEqual(self.left("LOT-A"), 1)
        surgery.delete()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("3"))

    def test_not_more_than_in_stock_and_same_size(self):
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist,
                                                                  [self.implant(36, "LOT-B"), self.implant(46, "LOT-B")]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("stock_choice", response.context["formset"].forms[0].errors)
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist,
                                                                  [self.implant(36, "LOT-A", implant_length="12")]))
        self.assertIn("stock_choice", response.context["formset"].forms[0].errors)
        self.assertFalse(Surgery.objects.exists())


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

    def test_totals_of_patients_surgeries_and_cases_per_procedure(self):
        context = self.find(result="sites").context
        self.assertEqual((context["overall"]["patients"], context["overall"]["surgeries"], context["overall"]["sites"]),
                         (2, 5, 5))
        totals = {row["code"]: row for row in context["procedure_totals"]}
        # 4 simple implant sites of 2 patients; the woman also has an open sinus and an extraction.
        self.assertEqual((totals["simple_implant"]["sites"], totals["simple_implant"]["patients"]), (4, 2))
        self.assertEqual((totals["open_sinus"]["sites"], totals["open_sinus"]["patients"]), (1, 1))
        self.assertEqual(totals["extraction"]["sites"], 1)
        # A click on a procedure filters by it; the extraction link looks at all sites, not implants only.
        self.assertIn("procedures_any=extraction", totals["extraction"]["query"])
        self.assertIn("result=sites", totals["extraction"]["query"])
        chosen = self.find(procedures_any="gbr").context
        self.assertTrue({row["code"]: row for row in chosen["procedure_totals"]}["gbr"]["active"])

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


class ProsthesisTests(TestCase):
    """Single crowns, bridges (units, implants, pontics) and full arches on the implants."""

    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        system = ImplantSystem.objects.get(company="Osstem")
        self.surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.dentist,
                                              date=timezone.localdate() - timedelta(days=120))
        self.sites = {}
        for tooth in (34, 37, 46, 12, 22):
            site = SurgerySite.objects.create(surgery=self.surgery, tooth=tooth, simple_implant=True, implant_system=system,
                                              implant_diameter=Decimal("4"), implant_length=Decimal("10"))
            SurgerySite.objects.filter(pk=site.pk).update(implant_status="uncovered")
            self.sites[tooth] = site
        for tooth in (35, 36):
            ToothState.objects.create(patient=self.patient, tooth=tooth, status=ToothState.Status.MISSING)
        self.client.login(username="dentist", password=PASSWORD)
        self.url = f"/surgery/prostheses/new/{self.patient.pk}/"

    def test_bridge_units_pontics_and_delivery(self):
        from apps.surgery.models import Prosthesis

        response = self.client.post(self.url, {
            "kind": "bridge", "teeth": "34-37", "implants": [self.sites[34].pk, self.sites[37].pk],
            "material": "zirconia", "retention": "screw", "status": "delivered", "delivered_on": "",
        })
        self.assertEqual(response.status_code, 302)
        bridge = Prosthesis.objects.get()
        self.assertEqual((bridge.units, bridge.implant_teeth, bridge.pontics), (4, [34, 37], [35, 36]))
        self.assertIn("4", bridge.label)
        self.assertEqual(bridge.delivered_on, timezone.localdate())
        for tooth in (34, 37):
            self.sites[tooth].refresh_from_db()
            self.assertEqual(self.sites[tooth].implant_status, "loaded")
        self.assertEqual(ToothState.objects.get(patient=self.patient, tooth=35).status, ToothState.Status.PONTIC)
        self.sites[46].refresh_from_db()
        self.assertEqual(self.sites[46].implant_status, "uncovered")  # not part of the bridge
        # The chart, the implant page and the finder show it.
        self.assertContains(self.client.get(f"/chart/patient/{self.patient.pk}/"), "34, 35, 36, 37")
        self.assertContains(self.client.get(f"/surgery/implant/{self.sites[34].pk}/"), bridge.get_kind_display())
        make_user("sup", "supervisor")
        self.client.login(username="sup", password=PASSWORD)
        found = self.client.get("/surgery/finder/", {"prosthesis": "bridge"}).context
        self.assertEqual(found["overall"]["implants"], 2)
        self.assertEqual(found["prosthesis_totals"][0]["units"], 4)
        self.assertEqual(self.client.get("/surgery/finder/", {"prosthesis": "none"}).context["overall"]["implants"], 3)

    def test_rules_for_each_kind(self):
        post = lambda **data: self.client.post(self.url, data)  # noqa: E731
        response = post(kind="single", implants=[self.sites[34].pk, self.sites[37].pk], status="planned")
        self.assertIn("implants", response.context["form"].errors)
        response = post(kind="single", implants=[self.sites[46].pk], status="planned")
        self.assertEqual(response.status_code, 302)  # the tooth is filled in from the implant
        response = post(kind="full_fixed", implants=[self.sites[12].pk, self.sites[34].pk], status="planned")
        self.assertIn("jaw", response.context["form"].errors)
        response = post(kind="full_fixed", jaw="upper", implants=[self.sites[12].pk, self.sites[34].pk], status="planned")
        self.assertIn("implants", response.context["form"].errors)  # 34 is in the lower jaw
        response = post(kind="overdenture", jaw="upper", implants=[self.sites[12].pk, self.sites[22].pk],
                        retention="locator", status="impression")
        self.assertEqual(response.status_code, 302)
        self.sites[12].refresh_from_db()
        self.assertEqual(self.sites[12].implant_status, "impression")
