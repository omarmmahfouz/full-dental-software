from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Bill, FawryMachine, PatientPayment, Service, create_bill
from apps.clinics.models import DoctorPayout, FeeRule
from apps.clinics.shares import owed, statement
from apps.core.models import Branch, UserProfile
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.dentists.models import Dentist
from apps.scheduling.models import Appointment, Room, RoomShift
from apps.stock.models import StockCategory, StockItem, StockMovement
from apps.stock.services import record_movement


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class PlaceMixin:
    def setUp(self):
        self.cia = setup_clinic()
        self.cic = Branch.objects.get(code="CIC")
        self.today = timezone.localdate()
        self.secretary = make_user("sec", "secretary")
        UserProfile.objects.update_or_create(user=self.secretary, defaults={"branch": self.cia})
        self.secretary.profile.places.set([self.cia, self.cic])
        make_user("sec2", "secretary")
        self.owner = make_user("owner", "owner")
        self.moderator = make_user("mod", "moderator")
        UserProfile.objects.update_or_create(user=self.moderator, defaults={"branch": self.cic})
        self.moderator.profile.places.set([self.cic])
        self.patient = make_patient(self.cia)
        self.walid = make_dentist("walid", kind=Dentist.Kind.SPECIALIST)
        self.walid.places.set([self.cic])
        self.mona = make_dentist("mona", kind=Dentist.Kind.FULLTIME)
        self.mona.places.set([self.cia])
        self.cic_room = Room.objects.filter(branch=self.cic).first()

    def work_at(self, username, code):
        self.client.login(username=username, password=PASSWORD)
        return self.client.post("/place/", {"place": code, "next": "/"})


class WorkingPlaceTests(PlaceMixin, TestCase):
    def test_cic_is_the_cairo_implant_center_with_rooms(self):
        self.assertEqual(self.cic.name_en, "Cairo Implant Center")
        self.assertEqual(Room.objects.filter(branch=self.cic, is_extra=False).count(), 3)
        self.assertEqual(FawryMachine.objects.count(), 2)

    def test_the_secretary_switches_place_and_the_pages_follow(self):
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/")
        self.assertEqual([p.code for p in page.context["working_places"]], ["CIA", "CIC"])
        self.assertIn('class="place-pill', page.content.decode())
        self.assertEqual(self.work_at("sec", "CIC").status_code, 302)
        page = self.client.get("/schedule/today/")
        self.assertEqual(page.context["current_branch"], self.cic)
        self.assertIn("place-CIC", page.content.decode())
        form = self.client.get("/schedule/appointments/new/").context["form"]
        self.assertEqual(set(form.fields["room"].queryset), set(Room.objects.filter(branch=self.cic)))
        self.assertIn(self.walid, form.fields["dentist"].queryset)
        self.assertNotIn(self.mona, form.fields["dentist"].queryset)  # she works at CIA only
        booking = {"scheduled_at_0": self.today.strftime("%d/%m/%Y"), "scheduled_at_1": "18:00",
                   "duration_minutes": 30, "dentist": self.walid.pk, "room": self.cic_room.pk}
        response = self.client.post("/schedule/appointments/new/", {"patient_lookup": self.patient.file_number, **booking})
        self.assertEqual(response.status_code, 200)  # each place has its own patients: CIA's are not found at CIC
        self.assertFalse(Appointment.objects.exists())
        # The patient moves to CIC: a new CIC file, the CIA file is closed.
        self.work_at("sec", "CIA")
        self.client.post(f"/patients/{self.patient.pk}/move/", {"place": "CIC"})
        self.patient.refresh_from_db()
        moved = self.patient.transferred_to
        self.assertEqual((self.patient.status, moved.branch), ("out", self.cic))
        self.work_at("sec", "CIC")
        response = self.client.post("/schedule/appointments/new/", {"patient_lookup": moved.file_number, **booking})
        self.assertEqual(response.status_code, 302)
        self.assertEqual((Appointment.objects.get().branch, Appointment.objects.get().patient), (self.cic, moved))

    def test_a_place_that_is_not_yours_cannot_be_chosen(self):
        self.assertEqual(self.work_at("sec", "PVT").status_code, 403)
        self.assertEqual(self.work_at("sec2", "CIC").status_code, 403)
        self.client.login(username="sec2", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["working_places"], [])  # one place: no switch
        self.assertEqual(self.work_at("owner", "PVT").status_code, 302)  # the owner works everywhere

    def test_a_shift_at_another_place_does_not_count(self):
        both = make_dentist("sherif", kind=Dentist.Kind.FULLTIME)
        both.places.set([self.cia, self.cic])
        RoomShift.objects.create(room=Room.objects.filter(branch=self.cia).first(), date=self.today,
                                 start_time=time(9), end_time=time(17), dentist=both)
        self.work_at("sec", "CIC")
        data = self.client.get(f"/schedule/dentist-day/?dentist={both.pk}&day={self.today:%Y-%m-%d}").json()
        self.assertFalse(data["working"])
        visit = Appointment.objects.create(branch=self.cic, patient=self.patient, dentist=both,
                                           scheduled_at=at(self.today, 10))
        self.assertIsNone(visit.find_shift())

    def test_people_and_dentists_get_their_places_in_settings(self):
        self.client.login(username="owner", password=PASSWORD)
        response = self.client.post(f"/settings/users/{self.secretary.pk}/", {
            "username": "sec", "first_name": "Sec", "roles": ["secretary"], "places": [self.cic.pk], "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user=self.secretary)
        self.assertEqual((list(profile.places.all()), profile.branch), ([self.cic], self.cic))
        response = self.client.post("/dentists/new/", {"full_name": "Dr. New", "kind": "freelancer", "places": [self.cic.pk],
                                                      "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Dentist.objects.get(full_name="Dr. New").places.all()), [self.cic])
        self.assertFalse(self.client.get("/settings/lists/places/").context["can_add"])
        self.assertEqual(self.client.get("/settings/lists/places/new/").status_code, 404)


class BillingPlaceTests(PlaceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.cic_implant = Service.objects.create(name_ar="زرعة CIC", name_en="CIC implant", price=Decimal("9000"),
                                                  branch=self.cic)
        self.consult = Service.objects.get(name_en="Consultation")
        Service.objects.filter(pk=self.consult.pk).update(price=Decimal("200"))
        self.machines = list(FawryMachine.objects.order_by("pk"))

    def test_services_offered_by_place(self):
        self.assertIn(self.cic_implant, Service.for_place(self.cic))
        self.assertNotIn(self.cic_implant, Service.for_place(self.cia))
        self.assertIn(self.consult, Service.for_place(self.cic))
        self.work_at("sec", "CIC")
        page = self.client.get(f"/billing/bills/new/?patient={self.patient.pk}")
        self.assertIn(self.cic_implant, page.context["lines"].forms[0].fields["service"].queryset)

    def test_a_bill_at_cic_is_counted_for_cic_with_its_fawry_machine(self):
        self.work_at("sec", "CIC")
        cic_patient = make_patient(self.cic, name="مريض مركز القاهرة", nid="29001011234599", phone="01001234599")
        data = {"patient_lookup": cic_patient.file_number, "billed_on": self.today.strftime("%d/%m/%Y"),
                "dentist": self.walid.pk, "lines-TOTAL_FORMS": 1, "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 1,
                "lines-MAX_NUM_FORMS": 1000, "lines-0-service": self.cic_implant.pk, "lines-0-teeth": "36",
                "pay-amount": "4000", "pay-method": "fawry"}
        response = self.client.post("/billing/bills/new/", data)
        self.assertEqual(response.status_code, 200)  # two machines: which one took the card?
        self.assertIn("fawry_machine", response.context["pay"].errors)
        response = self.client.post("/billing/bills/new/", {**data, "pay-fawry_machine": self.machines[1].pk})
        self.assertEqual(response.status_code, 302)
        bill = Bill.objects.get()
        self.assertEqual((bill.branch, bill.charges.get().branch, bill.charges.get().dentist), (self.cic, self.cic, self.walid))
        payment = PatientPayment.objects.get()
        self.assertEqual((payment.branch, payment.fawry_machine), (self.cic, self.machines[1]))
        move = payment.fawry_move
        self.assertEqual((move.branch, move.machine), (self.cic, self.machines[1]))
        page = self.client.get(f"/billing/fawry/?machine={self.machines[1].pk}")
        self.assertEqual(page.context["machine"], self.machines[1])
        self.assertEqual([m.pk for m in page.context["moves"]], [move.pk])  # the card payment she took
        self.assertEqual(move.created_by.username, "sec")
        # The payments of the day: the place worked in, or all places.
        self.assertEqual(self.client.get("/billing/payments/").context["page_obj"].paginator.count, 1)
        self.work_at("sec", "CIA")
        self.assertEqual(self.client.get("/billing/payments/").context["page_obj"].paginator.count, 0)
        self.assertEqual(self.client.get("/billing/payments/?place=all").context["page_obj"].paginator.count, 1)
        # The owner's balance sheet puts the money where it was paid; the owner sees what each machine holds.
        self.client.login(username="owner", password=PASSWORD)
        self.assertEqual(len(self.client.get(f"/billing/fawry/?machine={self.machines[1].pk}").context["per_machine"]), 2)
        page = self.client.get("/reports/balance/")
        cic_column = [c.code for c in page.context["columns"]].index("CIC")
        patients_row = page.context["income_rows"][0]
        self.assertEqual(patients_row["values"][cic_column], Decimal("4000"))

    def test_a_bill_from_a_visit_takes_the_visits_place(self):
        visit = Appointment.objects.create(branch=self.cic, patient=self.patient, scheduled_at=at(self.today, 12),
                                           dentist=self.walid)
        bill = create_bill(self.patient, [{"service": self.consult}], self.secretary, appointment=visit,
                           dentist=self.walid)
        self.assertEqual(bill.branch, self.cic)
        payment = PatientPayment.objects.create(patient=self.patient, bill=bill, amount=Decimal("200"), method="cash")
        self.assertEqual(payment.branch, self.cic)


class DoctorShareTests(PlaceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.implant = Service.objects.create(name_ar="زرعة CIC", name_en="CIC implant", price=Decimal("9000"),
                                              branch=self.cic)
        self.consult = Service.objects.get(name_en="Consultation")
        Service.objects.filter(pk=self.consult.pk).update(price=Decimal("200"))
        self.consult.refresh_from_db()
        self.start = self.today - timedelta(days=60)

    def visit(self, dentist, days_ago, minutes=30):
        day = self.today - timedelta(days=days_ago)
        visit = Appointment.objects.create(branch=self.cic, patient=self.patient, scheduled_at=at(day, 12), dentist=dentist,
                                           room=self.cic_room)
        visit.mark_arrived(at(day, 12))
        visit.mark_entered_room(at(day, 12, 5))
        visit.mark_left(at(day, 12, 5) + timedelta(minutes=minutes))
        visit.save()
        return visit

    def bill(self, dentist, lines, days_ago, paid):
        day = self.today - timedelta(days=days_ago)
        bill = create_bill(self.patient, lines, self.secretary, billed_on=day, dentist=dentist, branch=self.cic)
        if paid:
            PatientPayment.objects.create(patient=self.patient, bill=bill, amount=Decimal(paid), paid_on=day, method="cash")
        return bill

    def test_percentage_fixed_per_tooth_and_the_most_specific_rule(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("25"),
                               starts_on=self.start)
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, service=self.implant, method=FeeRule.Method.PER_UNIT,
                               value=Decimal("1500"), starts_on=self.start)
        self.bill(self.walid, [{"service": self.implant, "teeth": "36 46"}], 10, "5000")  # 2 teeth, partly paid
        self.bill(self.walid, [{"service": self.consult}], 5, "200")
        self.bill(self.walid, [{"service": self.consult}], 3, None)  # not paid yet: no percentage yet
        data = statement(self.walid, self.cic, self.start, self.today)
        shares = [line["share"] for line in data["lines"]]
        self.assertEqual(shares, [Decimal("3000"), Decimal("50.00"), Decimal("0.00")])
        self.assertEqual((data["billed"], data["collected"], data["share"]),
                         (Decimal("9400"), Decimal("5200"), Decimal("3050.00")))

    def test_per_visit_amounts_count_finished_visits_with_chair_time(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PER_VISIT, value=Decimal("400"),
                               starts_on=self.start)
        self.visit(self.walid, 4, minutes=40)
        self.visit(self.walid, 2, minutes=20)
        Appointment.objects.create(branch=self.cic, patient=self.patient, dentist=self.walid,
                                   scheduled_at=at(self.today + timedelta(days=1), 12))  # not come yet
        data = statement(self.walid, self.cic, self.start, self.today + timedelta(days=2))
        self.assertEqual((data["visit_count"], data["chair_minutes"], data["share"]), (2, 60, Decimal("800")))

    def test_a_new_rule_from_a_date_leaves_older_services_as_they_were(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("20"),
                               starts_on=self.start)
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("40"),
                               starts_on=self.today - timedelta(days=5))
        self.bill(self.walid, [{"service": self.consult}], 10, "200")
        self.bill(self.walid, [{"service": self.consult}], 2, "200")
        shares = [line["share"] for line in statement(self.walid, self.cic, self.start, self.today)["lines"]]
        self.assertEqual(shares, [Decimal("40.00"), Decimal("80.00")])

    def test_payments_to_the_doctor_and_what_is_still_owed(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("50"),
                               starts_on=self.start)
        self.bill(self.walid, [{"service": self.consult}], 20, "200")
        self.bill(self.walid, [{"service": self.consult}], 2, "200")
        self.client.login(username="mod", password=PASSWORD)
        url = f"/clinics/doctor/{self.walid.pk}/?place=CIC"
        response = self.client.post(url, {"amount": "150", "paid_on": self.today.strftime("%d/%m/%Y"), "method": "cash"})
        self.assertEqual(response.status_code, 302)
        payout = DoctorPayout.objects.get()
        self.assertEqual((payout.branch, payout.created_by), (self.cic, self.moderator))
        self.assertEqual(owed(self.walid, self.cic, self.today), Decimal("50.00"))  # 100 + 100 earned, 150 paid
        period = f"date_from={self.start:%d/%m/%Y}&date_to={self.today:%d/%m/%Y}"  # also on the 1st of a month
        page = self.client.get(f"/clinics/?place=CIC&{period}")
        row = next(r for r in page.context["rows"] if r["dentist"] == self.walid)
        self.assertEqual((row["share"], row["paid_out"], row["owed"]), (Decimal("200.00"), Decimal("150"), Decimal("50.00")))
        # The balance sheet counts it as a cost of CIC.
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/reports/balance/")
        cic_column = [c.code for c in page.context["columns"]].index("CIC")
        doctors = next(r for r in page.context["cost_rows"] if "doctors" in str(r["label"]))
        self.assertEqual(doctors["values"][cic_column], Decimal("150"))

    def test_who_sees_the_shares(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("30"),
                               starts_on=self.start)
        self.client.login(username="sec", password=PASSWORD)
        for url in ("/clinics/", "/clinics/rules/", "/clinics/report/", f"/clinics/doctor/{self.walid.pk}/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.login(username="walid", password=PASSWORD)  # a doctor sees their own statement only
        self.assertEqual(self.client.get("/clinics/mine/")["Location"], f"/clinics/doctor/{self.walid.pk}/")
        page = self.client.get(f"/clinics/doctor/{self.walid.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context["payout_form"])
        self.assertEqual(self.client.post(f"/clinics/doctor/{self.walid.pk}/", {"amount": "10"}).status_code, 200)
        self.assertFalse(DoctorPayout.objects.exists())
        self.assertEqual(self.client.get(f"/clinics/doctor/{self.mona.pk}/").status_code, 403)
        self.assertTrue(self.client.get("/").context["my_fee_rules"])
        self.client.login(username="mod", password=PASSWORD)
        for url in ("/clinics/", "/clinics/rules/", "/clinics/report/", "/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual([item["url"] for item in self.client.get("/").context["bottom_nav"]],
                         ["/", "/clinics/", "/clinics/report/", "/clinics/rules/"])

    def test_the_moderator_sets_the_rules(self):
        self.client.login(username="mod", password=PASSWORD)
        form = self.client.get("/clinics/rules/new/?place=CIC").context["form"]
        self.assertIn(self.walid, form.fields["dentist"].queryset)
        self.assertNotIn(self.mona, form.fields["dentist"].queryset)
        self.assertIn(self.implant, form.fields["service"].queryset)
        base = {"dentist": self.walid.pk, "starts_on": self.today.strftime("%d/%m/%Y"), "is_active": "on"}
        bad = self.client.post("/clinics/rules/new/?place=CIC", {**base, "method": "percent", "value": "130"})
        self.assertIn("value", bad.context["form"].errors)
        bad = self.client.post("/clinics/rules/new/?place=CIC", {**base, "method": "per_visit", "value": "300",
                                                                 "service": self.implant.pk})
        self.assertIn("service", bad.context["form"].errors)
        response = self.client.post("/clinics/rules/new/?place=CIC", {**base, "method": "per_unit", "value": "1500",
                                                                      "service": self.implant.pk})
        self.assertEqual(response.status_code, 302)
        rule = FeeRule.objects.get()
        self.assertEqual((rule.branch, rule.service, rule.value), (self.cic, self.implant, Decimal("1500")))
        page = self.client.get("/clinics/rules/?place=CIC")
        self.assertEqual([d for d, _rules in page.context["by_doctor"]], [self.walid])

    def test_clinic_report_and_home_card(self):
        FeeRule.objects.create(dentist=self.walid, branch=self.cic, method=FeeRule.Method.PERCENT, value=Decimal("30"),
                               starts_on=self.start)
        visit = self.visit(self.walid, 1, minutes=45)
        bill = create_bill(self.patient, [{"service": self.consult}], self.secretary, appointment=visit, dentist=self.walid,
                           billed_on=self.today - timedelta(days=1))
        PatientPayment.objects.create(patient=self.patient, bill=bill, amount=Decimal("200"), method="cash",
                                      paid_on=self.today - timedelta(days=1))
        item = StockItem.objects.create(name="Gloves", category=StockCategory.objects.first(), unit_cost=Decimal("10"))
        record_movement(item, StockMovement.Kind.IN, 100, branch=self.cia)
        record_movement(item, StockMovement.Kind.OUT, 5, branch=self.cic, moved_at=at(self.today - timedelta(days=1), 12))
        record_movement(item, StockMovement.Kind.OUT, 7, branch=self.cia, moved_at=at(self.today - timedelta(days=1), 12))
        self.client.login(username="owner", password=PASSWORD)
        day_from = (self.today - timedelta(days=3)).strftime("%d/%m/%Y")
        page = self.client.get(f"/clinics/report/?place=CIC&date_from={day_from}&date_to={self.today:%d/%m/%Y}")
        c = page.context
        self.assertEqual((c["collected"], c["visit_count"], c["chair_minutes"], c["stock_used"]),
                         (Decimal("200"), 1, 45, Decimal("50")))
        self.assertEqual(c["left"], Decimal("200") - Decimal("60.00") - Decimal("50"))
        self.client.post("/place/", {"place": "CIC", "next": "/"})  # round 14: the owner's home shows that place
        cards = self.client.get("/").context["clinic_cards"]  # this month, at a place paying by rules
        self.assertEqual([card["place"] for card in cards], [self.cic])
        self.client.post("/place/", {"place": "CIA", "next": "/"})
        self.assertEqual(self.client.get("/").context["clinic_cards"], [])


class StockPlaceTests(PlaceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.stock = make_user("store", "stock")
        self.category = StockCategory.objects.first()
        self.shared = StockItem.objects.create(name="Gloves", category=self.category, unit_cost=Decimal("2"))
        self.cic_only = StockItem.objects.create(name="CIC drapes", category=self.category, branch=self.cic,
                                                 unit_cost=Decimal("30"))
        record_movement(self.shared, StockMovement.Kind.IN, 50)
        record_movement(self.cic_only, StockMovement.Kind.IN, 20, branch=self.cic)

    def use(self, place, item, quantity):
        return self.client.post("/stock/take-out/", {
            "branch": place.pk, "destination": "Room 1", "kind": "out", "lines-TOTAL_FORMS": 1, "lines-INITIAL_FORMS": 0,
            "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000, "lines-0-item": item.pk, "lines-0-quantity": quantity})

    def test_each_use_records_its_place_and_material_of_one_place_stays_there(self):
        self.client.login(username="store", password=PASSWORD)
        self.assertEqual(self.use(self.cic, self.shared, 4).status_code, 302)
        self.assertEqual(self.use(self.cia, self.shared, 6).status_code, 302)
        self.assertEqual(self.use(self.cia, self.cic_only, 1).status_code, 200)  # CIC's drapes are not for CIA
        self.assertEqual(self.use(self.cic, self.cic_only, 3).status_code, 302)
        out = StockMovement.objects.filter(kind="out")
        self.assertEqual(sorted((m.item.name, m.branch.code, m.quantity) for m in out),
                         [("CIC drapes", "CIC", Decimal("3")), ("Gloves", "CIA", Decimal("6")), ("Gloves", "CIC", Decimal("4"))])
        page = self.client.get("/stock/movements/")
        use = {row["place"].code: row["value"] for row in page.context["use_by_place"]}
        self.assertEqual(use, {"CIC": Decimal("98"), "CIA": Decimal("12")})  # 4x2 + 3x30, 6x2
        items = self.client.get("/stock/?place=CIC").context["page_obj"]
        self.assertEqual([i.name for i in items], ["CIC drapes"])
        items = self.client.get("/stock/?place=shared").context["page_obj"]
        self.assertEqual([i.name for i in items], ["Gloves"])

    def test_implants_of_a_place_are_offered_there_and_taken_out_for_its_surgery(self):
        from apps.stock.implants import lot_choices, take_implants
        from apps.surgery.models import ImplantSystem, Surgery, SurgerySite

        system = ImplantSystem.objects.first()
        cic_implant = StockItem.objects.create(name="Implant (CIC)", category=self.category, branch=self.cic,
                                               implant_system=system, implant_diameter=Decimal("4"),
                                               implant_length=Decimal("10"))
        record_movement(cic_implant, StockMovement.Kind.IN, 3, lot="L1", branch=self.cic)
        self.assertTrue(lot_choices(system=system.pk, branch=self.cic))
        self.assertFalse(lot_choices(system=system.pk, branch=self.cia))
        surgery = Surgery.objects.create(branch=self.cic, patient=self.patient, operator_1=self.walid)
        SurgerySite.objects.create(surgery=surgery, tooth=36, simple_implant=True, implant_system=system,
                                   implant_stock_item=cic_implant, lot_number="L1", implant_diameter=Decimal("4"),
                                   implant_length=Decimal("10"))
        take_implants(surgery, self.stock)
        self.assertEqual(StockMovement.objects.get(kind="out").branch, self.cic)
