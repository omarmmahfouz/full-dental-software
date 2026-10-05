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


class DesignTests(TestCase):
    """Round 10: the surgery chart designed like a scanner's order form: implants and pontics, a full arch planned
    by itself, the delivery checklist, and the visit after the surgery."""

    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.system = ImplantSystem.objects.get(company="Osstem")
        for tooth in (15, 13, 11, 21, 23, 25):
            ToothState.objects.create(patient=self.patient, tooth=tooth, status=ToothState.Status.MISSING)
        self.client.login(username="dentist", password=PASSWORD)

    def implant(self, tooth, **extra):
        site = {"tooth": tooth, "simple_implant": True, "implant_system": self.system.pk, "implant_diameter": "3.75",
                "implant_length": "11.5"}
        site.update(extra)
        return site

    def test_the_page_offers_the_designer(self):
        page = self.client.get(f"/surgery/new/?patient={self.patient.pk}")
        self.assertContains(page, "data-arch-designer")
        self.assertContains(page, 'id="implant-sequence"')
        self.assertContains(page, "data-arch-pontics")  # the hidden field of the pontics
        self.assertIn("3.75", page.context["diameters"])

    def test_full_arch_with_pontics(self):
        sites = [self.implant(t) for t in (16, 14, 12, 22, 24, 26)]
        sites[0]["closed_sinus"] = True
        response = self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, sites,
                                                                  pontics="25, 23, 21, 11, 13, 15, 14"))
        surgery = Surgery.objects.get()
        self.assertRedirects(response, surgery.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(surgery.pontics, "15, 13, 11, 21, 23, 25")  # 14 has an implant: not a pontic
        self.assertEqual(SurgerySite.objects.get(tooth=12).implant_diameter, Decimal("3.75"))
        states = dict(ToothState.objects.filter(patient=self.patient).values_list("tooth", "status"))
        self.assertEqual(states[15], ToothState.Status.PONTIC)  # no longer "missing"
        self.assertEqual(states[16], ToothState.Status.IMPLANT)
        from apps.surgery.models import Prosthesis

        arch = Prosthesis.objects.get()
        self.assertEqual((arch.kind, arch.jaw, arch.status), ("full_fixed", "upper", "planned"))
        self.assertEqual(arch.pontics, [15, 13, 11, 21, 23, 25])
        self.assertEqual(len(arch.implant_teeth), 6)
        page = self.client.get(surgery.get_absolute_url())
        self.assertContains(page, "arch-view")
        self.assertContains(page, "bar-start")  # the bar under the full arch
        self.assertEqual(page.context["follow_up"]["days"], 2)  # a sinus lift: checked after 2 days
        # Saving again plans nothing twice.
        from apps.surgery.prostheses import plan_from_surgery

        self.assertEqual(plan_from_surgery(surgery, None), [])

    def test_bridges_singles_and_an_extraction_kept_as_a_pontic(self):
        from apps.surgery.models import Prosthesis

        ToothState.objects.create(patient=self.patient, tooth=45)
        sites = [self.implant(46), self.implant(44), {"tooth": 45, "extraction": True}, self.implant(36),
                 self.implant(37)]
        self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, sites, pontics="45"))
        self.assertEqual(ToothState.objects.get(patient=self.patient, tooth=45).status, ToothState.Status.PONTIC)
        kinds = sorted((p.kind, p.teeth) for p in Prosthesis.objects.all())
        self.assertEqual(kinds, [("bridge", "46, 45, 44"), ("single", "36"), ("single", "37")])
        surgery = Surgery.objects.get()
        self.assertEqual(self.client.get(surgery.get_absolute_url()).context["follow_up"]["days"], 7)

    def test_the_delivery_checklist(self):
        from apps.surgery.models import DeliveryCheck, Prosthesis

        self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [self.implant(36)]))
        crown = Prosthesis.objects.get()
        Prosthesis.objects.filter(pk=crown.pk).update(retention=Prosthesis.Retention.SCREW)
        crown.refresh_from_db()
        page = self.client.get(f"/surgery/prostheses/{crown.pk}/delivery/")
        codes = [code for _group, rows in page.context["groups"] for code, *_rest in rows]
        self.assertIn("torque", codes)
        self.assertIn("contacts", codes)
        self.assertNotIn("cement_cleaned", codes)  # screw-retained
        self.assertNotIn("attachments", codes)  # not removable
        response = self.client.post(f"/surgery/prostheses/{crown.pk}/delivery/", {
            "tick": ["lab_match", "shade", "torque", "not-a-point"], "date": "01/09/2026", "torque_ncm": "35",
            "action": "save"})
        self.assertRedirects(response, f"/surgery/prostheses/{crown.pk}/delivery/", fetch_redirect_response=False)
        check = DeliveryCheck.objects.get()
        self.assertEqual(check.ticked, ["lab_match", "shade", "torque"])
        crown.refresh_from_db()
        self.assertEqual(crown.status, "planned")  # only saved
        self.client.post(f"/surgery/prostheses/{crown.pk}/delivery/", {
            "tick": codes, "date": "01/09/2026", "torque_ncm": "35", "action": "deliver"})
        crown.refresh_from_db()
        self.assertEqual((crown.status, crown.delivered_on.isoformat()), ("delivered", "2026-09-01"))
        self.assertEqual(SurgerySite.objects.get().implant_status, SurgerySite.ImplantStatus.LOADED)
        self.assertEqual(DeliveryCheck.objects.get().missing(), [])
        overdenture = Prosthesis(kind=Prosthesis.Kind.OVERDENTURE, retention=Prosthesis.Retention.LOCATOR)
        codes = [code for _group, rows in DeliveryCheck.items_for(overdenture) for code, *_rest in rows]
        self.assertIn("attachments", codes)
        self.assertNotIn("xray", codes)

    def test_the_visit_after_the_surgery_goes_to_the_reception(self):
        from apps.scheduling.models import PatientRequest

        self.client.post("/surgery/new/", surgery_data(self.patient, self.dentist, [self.implant(36)]))
        surgery = Surgery.objects.get()
        response = self.client.post(f"/surgery/{surgery.pk}/follow-up/")
        self.assertRedirects(response, surgery.get_absolute_url(), fetch_redirect_response=False)
        self.client.post(f"/surgery/{surgery.pk}/follow-up/")  # asked twice: one request
        request = PatientRequest.objects.get()
        self.assertEqual(request.status, PatientRequest.Status.APPROVED)
        self.assertEqual(request.step_type.name_en, "Suture removal")
        self.assertEqual(request.wanted_from, surgery.date + timedelta(days=7))
        page = self.client.get(f"/prescriptions/patient/{self.patient.pk}/instructions/?surgery={surgery.pk}")
        self.assertContains(page, "follow-up-print")


class Round13GroupingTests(TestCase):
    """One-tap groupings: full arch or not, guided or freehand, crown / bridge / full arch, splitting, expansion."""

    setUp = FinderTests.setUp
    find = FinderTests.find

    def test_full_arch_guided_splitting_and_expansion(self):
        from apps.surgery.models import Prosthesis

        woman = SurgerySite.objects.get(tooth=26).surgery.patient
        all_on_four = Surgery.objects.create(branch=self.branch, patient=woman, operator_1=self.dentist,
                                             date=timezone.localdate() - timedelta(days=30))
        sites = []
        for tooth in (32, 34, 42, 44):
            obj = SurgerySite.objects.create(surgery=all_on_four, tooth=tooth, guided=True, simple_implant=True,
                                             splitting=tooth == 34, expansion=tooth == 44, isq=70)
            SurgerySite.objects.filter(pk=obj.pk).update(implant_status="placed")
            sites.append(obj)
        bridge = Prosthesis.objects.create(patient=woman, kind=Prosthesis.Kind.BRIDGE, teeth="35-37")
        bridge.implants.add(SurgerySite.objects.get(tooth=36))
        self.assertEqual(self.find(full_arch="yes").context["overall"]["implants"], 4)
        self.assertEqual(self.find(full_arch="no").context["overall"]["implants"], 4)
        groups = {g["key"]: g for g in self.find(group_by="full_arch").context["groups"]}
        self.assertEqual((groups["Full-arch case"]["implants"], groups["Not full arch"]["implants"]), (4, 4))
        self.assertEqual(groups["Full-arch case"]["isq"], 70)
        guided = {g["key"]: g["implants"] for g in self.find(group_by="guided").context["groups"]}
        self.assertEqual(guided, {"Guided (surgical guide)": 4, "Freehand": 4})
        self.assertEqual({g["key"]: g["implants"] for g in self.find(group_by="splitting").context["groups"]},
                         {"Splitting": 1, "No splitting": 7})
        self.assertEqual({g["key"]: g["implants"] for g in self.find(group_by="expansion").context["groups"]},
                         {"Expansion": 1, "No expansion": 7})
        kinds = {g["key"]: g["implants"] for g in self.find(group_by="prosthesis").context["groups"]}
        self.assertEqual(kinds["Bridge on implants"], 1)
        page = self.find()
        self.assertTrue(any(g["query"].endswith("group_by=full_arch") for g in page.context["quick_groups"]))
        self.assertContains(page, "Full-arch cases")


class Round15ImplantLifeTests(TestCase):
    """Round 15: the checks and the complications of an implant, the finder for papers, the treatment page that
    asks for the teeth first and shows their state."""

    def setUp(self):
        self.branch = setup_clinic()
        self.dentist = make_dentist("dentist", kind="fulltime")
        self.owner = make_user("owner", "owner")
        self.patient = make_patient(self.branch, assigned_dentist=self.dentist)
        self.system = ImplantSystem.objects.first()
        self.surgery = Surgery.objects.create(branch=self.branch, patient=self.patient, operator_1=self.dentist,
                                              date=timezone.localdate() - timedelta(days=200))
        self.site = SurgerySite.objects.create(surgery=self.surgery, tooth=36, simple_implant=True,
                                               implant_system=self.system, implant_diameter=Decimal("4"),
                                               implant_length=Decimal("10"))
        ToothState.objects.create(patient=self.patient, tooth=36, status=ToothState.Status.IMPLANT,
                                  implant_site=self.site)
        self.client.login(username="dentist", password=PASSWORD)

    def test_a_check_finds_the_class_of_the_tissues(self):
        from apps.surgery.models import ImplantFollowUp, PeriImplantStatus

        day = timezone.localdate().strftime("%d/%m/%Y")
        response = self.client.post(f"/surgery/implant/{self.site.pk}/check/", {
            "checked_on": day, "dentist": self.dentist.pk, "probing_depth": "6", "bleeding": "true",
            "suppuration": "false", "bone_loss": "3.5", "isq": "70"})
        self.assertRedirects(response, f"/surgery/implant/{self.site.pk}/", fetch_redirect_response=False)
        check = ImplantFollowUp.objects.get()
        self.assertEqual(check.status, PeriImplantStatus.PERI_IMPLANTITIS)
        self.assertEqual(check.patient, self.patient)
        self.assertAlmostEqual(check.months_since_placement, 6.6, places=1)
        self.assertEqual(ImplantFollowUp(site=self.site, bleeding=True).classify(), PeriImplantStatus.MUCOSITIS)
        self.assertEqual(ImplantFollowUp(site=self.site, bleeding=False).classify(), PeriImplantStatus.HEALTH)
        page = self.client.get(f"/surgery/implant/{self.site.pk}/")
        self.assertEqual(list(page.context["checks"]), [check])

    def test_a_paresthesia_needs_its_nerve_and_a_removal_fails_the_implant(self):
        from apps.surgery.models import ImplantComplication

        url = f"/surgery/implant/{self.site.pk}/complication/"
        day = timezone.localdate().strftime("%d/%m/%Y")
        data = {"kind": "paresthesia", "found_on": day, "severity": "moderate", "outcome": "open"}
        response = self.client.post(url, data)
        self.assertIn("nerve", response.context["form"].errors)
        self.client.post(url, {**data, "nerve": "ian", "side": "left", "area": "lower lip"})
        nerve = ImplantComplication.objects.get()
        self.assertEqual((nerve.group, nerve.timing), ("nerve", "healing"))  # not loaded yet
        self.client.post(url, {"kind": "late_failure", "found_on": day, "severity": "severe", "outcome": "implant_lost",
                               "treatment": "removed"})
        self.site.refresh_from_db()
        self.assertEqual(self.site.implant_status, SurgerySite.ImplantStatus.FAILED)
        self.assertEqual(ToothState.objects.get(patient=self.patient, tooth=36).status, ToothState.Status.MISSING)
        lost = ImplantComplication.objects.get(kind="late_failure")
        self.assertEqual((lost.group, lost.resolved_on), ("failure", timezone.localdate()))

    def test_the_finder_and_its_excel(self):
        from apps.surgery.models import ImplantComplication

        ImplantComplication.objects.create(site=self.site, kind="screw_loosening", found_on=timezone.localdate())
        ImplantComplication.objects.create(site=self.site, kind="mucositis", found_on=timezone.localdate(),
                                           outcome="resolved")
        self.client.logout()
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/surgery/complications/")
        self.assertEqual(len(page.context["rows"]), 2)
        self.assertEqual(page.context["implants"], 1)
        self.assertEqual(page.context["open"], 1)
        self.assertEqual(len(self.client.get("/surgery/complications/?group=mechanical").context["rows"]), 1)
        excel = self.client.get("/surgery/complications/?excel=1")
        self.assertEqual(excel["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.client.logout()
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/surgery/complications/").status_code, 403)

    def test_the_teeth_first_and_a_check_after_the_step(self):
        from apps.clinical.models import TreatmentStep

        status = self.client.get(f"/clinical/steps/teeth-status/?patient={self.patient.pk}&teeth=36, 11").json()
        teeth = {row["tooth"]: row for row in status["teeth"]}
        self.assertEqual(teeth[36]["implant"]["label"], self.site.implant_label)
        self.assertIn("implant_teeth", status["groups"])
        self.assertEqual(teeth[11]["now"], "sound")
        check = TreatmentStepType.objects.get(name_en="Implant check (follow-up)")
        self.assertEqual((check.group, check.implant_record), ("implant_care", "follow_up"))
        response = self.client.post(f"/clinical/steps/new/?patient={self.patient.pk}", {
            "patient_lookup": self.patient.file_number, "performed_at_0": timezone.localdate().strftime("%d/%m/%Y"),
            "performed_at_1": "10:00", "step_type": check.pk, "teeth": "36", "operator": self.dentist.pk})
        step = TreatmentStep.objects.get()
        self.assertRedirects(response, f"/surgery/implant/{self.site.pk}/check/?step={step.pk}",
                             fetch_redirect_response=False)

    def test_the_bill_of_the_step_and_a_changed_price(self):
        from apps.billing.models import Bill, Service
        from apps.clinical.models import TreatmentStep
        from apps.core.models import Notification

        moderator = make_user("mod", "moderator")
        filling = TreatmentStepType.objects.get(name_en="Composite restoration")
        self.assertEqual(filling.service.name_en, "Filling")
        Service.objects.filter(pk=filling.service_id).update(price=Decimal("500"))
        info = self.client.get(f"/clinical/steps/bill-info/?service={filling.service_id}&patient={self.patient.pk}")
        self.assertEqual(info.json()["price"], "500.00")
        data = {"patient_lookup": self.patient.file_number,
                "performed_at_0": timezone.localdate().strftime("%d/%m/%Y"), "performed_at_1": "10:00",
                "step_type": filling.pk, "teeth": "46", "operator": self.dentist.pk,
                "bill_service": filling.service_id, "bill_price": "500"}
        self.client.post(f"/clinical/steps/new/?patient={self.patient.pk}", data)
        self.assertFalse(Notification.objects.filter(recipient=self.owner, title__startswith="Price").exists())
        self.client.post(f"/clinical/steps/new/?patient={self.patient.pk}", {**data, "bill_price": "350"})
        self.assertEqual(TreatmentStep.objects.count(), 2)
        self.assertEqual(Bill.objects.count(), 2)
        for person in (self.owner, moderator):
            self.assertTrue(Notification.objects.filter(recipient=person, title__startswith="Price").exists())
        self.assertEqual(self.client.get(f"/clinical/steps/bill-info/?patient={self.patient.pk}").json()["owes"],
                         "850.00")
