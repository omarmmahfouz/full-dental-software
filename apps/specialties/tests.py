"""El Khadem Dental Clinic: the place and its look, the specialists and their charts, referrals, the doctors' own
prices and shares (40% of their own patients, 30% of the clinic's, after the lab and implant cost), the shared
rooms, and the printed treatment plan and lab request."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Charge, PatientPayment, Service, create_bill
from apps.charting.models import PlanItem, ToothState, TreatmentPlan
from apps.clinical.models import ChartEffect, Lab, LabRequest, LabWorkType, TreatmentStep, TreatmentStepType
from apps.clinics.models import DoctorPrice, FeeRule
from apps.clinics.prices import price_and_cost
from apps.clinics.shares import pick_rule, statement, totals
from apps.core.models import Branch, ChangeRequest, ClinicSettings, Notification, UserProfile
from apps.core.roles import is_only_dentist
from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic
from apps.dentists.models import Dentist
from apps.patients.models import Patient, ReferralSource
from apps.scheduling.free_times import free_times
from apps.scheduling.models import Appointment, Room
from apps.scheduling.rooms import change_room, free_room
from apps.specialties.models import EndoCase, EndoCanal, OrthoCase, Referral, ShadeRecord, TMJExam

S = Dentist.Specialty


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class KhademMixin:
    def setUp(self):
        self.cia = setup_clinic()
        self.place = Branch.objects.get(code="PVT")
        self.today = timezone.localdate()
        self.tomorrow = self.today + timedelta(days=1)
        if self.tomorrow.weekday() in self.place.closed_weekdays:
            self.tomorrow += timedelta(days=1)
        self.rooms = list(Room.objects.filter(branch=self.place, is_extra=False).order_by("sort_order"))
        self.reception = self.person("khadem", "secretary")
        self.amr_user = self.person("amr", "dentist", "moderator")
        self.amr = self.doctor("amr", S.PROSTHODONTIST, user=self.amr_user)
        self.endo_user = self.person("endo", "dentist")
        self.endo = self.doctor("endo", S.ENDODONTIST, user=self.endo_user)
        self.tmj = self.doctor("tmj", S.TMJ)
        self.surgeon = self.doctor("surgeon", S.ORAL_SURGEON)
        self.patient = make_patient(self.place, name="كريم مصطفى عبد الحميد")
        self.own_patient = make_patient(self.place, name="رنا سمير إبراهيم", nid="29609071234567",
                                        phone="01101000007", brought_by=self.surgeon)

    def person(self, username, *roles):
        user = make_user(username, *roles)
        UserProfile.objects.update_or_create(user=user, defaults={"branch": self.place})
        user.profile.places.set([self.place])
        return user

    def doctor(self, name, specialty, user=None):
        dentist = Dentist.objects.create(full_name=f"Dr. {name.title()}", kind=Dentist.Kind.SPECIALIST,
                                         specialty=specialty, user=user, branch=self.place)
        dentist.places.set([self.place])
        return dentist

    def login(self, username):
        self.client.login(username=username, password=PASSWORD)


# ------------------------------------------------------------------ the place
class KhademPlaceTests(KhademMixin, TestCase):
    def test_el_khadem_is_set_up_with_its_look_and_four_shared_rooms(self):
        self.assertEqual(self.place.name_en, "El Khadem Dental Clinic")
        self.assertEqual((self.place.badge, self.place.theme, self.place.rooms_shared), ("EK", "elite", True))
        self.assertEqual(len(self.rooms), 4)
        self.assertTrue(self.patient.file_number.startswith("EK-"))
        self.assertTrue(self.place.mark_url.endswith("khadem-mark.svg"))
        # Running the setup again changes nothing the owner set.
        Branch.objects.filter(pk=self.place.pk).update(name_en="El Khadem", tagline="Mine")
        setup_clinic()
        self.place.refresh_from_db()
        self.assertEqual((self.place.name_en, self.place.tagline), ("El Khadem", "Mine"))
        self.assertEqual(Room.objects.filter(branch=self.place, is_extra=False).count(), 4)

    def test_the_screens_take_the_elite_look_of_the_place(self):
        self.login("khadem")
        page = self.client.get("/").content.decode()
        self.assertIn("theme-elite", page)
        self.assertIn("place-PVT", page)
        self.assertIn("khadem-mark.svg", page)
        self.login("amr")
        self.assertIn("theme-elite", self.client.get("/specialists/").content.decode())

    def test_the_login_page_takes_the_look_of_the_place_of_this_device(self):
        self.client.logout()
        page = self.client.get("/login/?place=EK")
        self.assertContains(page, "login-page place-PVT theme-elite")
        self.assertContains(page, "khadem-mark.svg")
        self.assertEqual(page.cookies["device_place"].value, "PVT")
        self.assertContains(self.client.get("/login/"), "login-page place-PVT theme-elite")  # remembered on this PC
        self.client.cookies.pop("device_place")
        self.assertNotContains(self.client.get("/login/"), "login-page place-PVT")

    def test_someone_logging_in_at_a_place_they_work_starts_there(self):
        owner = make_user("owner", "owner")
        self.client.get("/login/?place=EK")
        self.client.post("/login/", {"username": "owner", "password": PASSWORD})
        self.assertEqual(self.client.get("/").context["current_branch"], self.place)
        self.client.logout()  # clears the cookies too
        # A person with one place makes it this device's place.
        response = self.client.post("/login/", {"username": "khadem", "password": PASSWORD})
        self.assertEqual(response.cookies["device_place"].value, "PVT")
        self.assertTrue(owner.pk)

    def test_the_place_logo_is_shown_without_login_only_when_there_is_one(self):
        self.client.logout()
        self.assertEqual(self.client.get("/place/PVT/logo/").status_code, 404)

    def test_the_reception_of_el_khadem_does_not_see_the_academy(self):
        self.login("khadem")
        self.assertEqual(self.client.get("/academy/candidates/").status_code, 403)
        self.assertNotContains(self.client.get("/"), "/academy/candidates/")

    def test_the_whatsapp_list_shows_the_patients_of_the_place_only(self):
        cia_patient = make_patient(self.cia, name="مريض الأكاديمية الأول", nid="29001011234599", phone="01001234599")
        Appointment.objects.create(branch=self.cia, patient=cia_patient, scheduled_at=at(self.tomorrow, 13))
        Appointment.objects.create(branch=self.place, patient=self.patient, scheduled_at=at(self.tomorrow, 13))
        self.login("khadem")
        page = self.client.get("/schedule/whatsapp/").content.decode()
        self.assertIn(self.patient.full_name, page)
        self.assertNotIn(cia_patient.full_name, page)

    def test_changes_by_the_reception_wait_for_the_manager_of_the_place(self):
        head = make_user("head", "head_cia")  # the head of CIA works at CIA only
        self.login("khadem")
        data = {"full_name": self.patient.full_name, "id_type": "nid", "national_id": self.patient.national_id,
                "phone_primary": self.patient.phone_primary, "preferred_phone": "primary", "missing_teeth": "unknown",
                "referral_source": ReferralSource.objects.filter(asks_for_patient=False).first().pk,
                "status": "active", "phone_secondary": "01223344556", "marital_status": "married", "occupation": "تاجر",
                "city": "الدقي"}
        self.client.post(f"/patients/{self.patient.pk}/edit/", data)
        change = ChangeRequest.objects.get()
        self.assertEqual(change.branch, self.place)
        self.assertTrue(Notification.objects.filter(recipient=self.amr_user, url="/approvals/").exists())
        self.assertFalse(Notification.objects.filter(recipient=head, url="/approvals/").exists())
        self.login("amr")
        self.assertContains(self.client.get("/approvals/"), self.patient.full_name)
        self.client.post(f"/approvals/{change.pk}/", {"action": "approve"})
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone_secondary, "01223344556")
        # The head of CIA does not see El Khadem's changes; the manager edits directly.
        self.login("head")
        self.assertNotContains(self.client.get("/approvals/"), self.patient.full_name)

    def test_a_doctor_who_manages_the_clinic_sees_everything_there(self):
        self.assertFalse(is_only_dentist(self.amr_user))
        self.assertTrue(is_only_dentist(self.endo_user))
        self.login("amr")
        self.assertEqual(self.client.get("/schedule/day/").status_code, 200)  # the day, without booking
        self.login("endo")
        self.assertEqual(self.client.get("/schedule/day/").status_code, 403)

    def test_the_patient_form_asks_which_doctor_brought_the_patient_at_a_clinic_only(self):
        self.login("khadem")
        form = self.client.get("/patients/new/").context["form"]
        self.assertIn("brought_by", form.fields)
        self.assertIn(self.surgeon, form.fields["brought_by"].queryset)
        cia_secretary = make_user("ciasec", "secretary")
        self.client.login(username="ciasec", password=PASSWORD)
        self.assertNotIn("brought_by", self.client.get("/patients/new/").context["form"].fields)
        self.assertTrue(cia_secretary.pk)


# ------------------------------------------------------------------ money
class KhademShareTests(KhademMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.implant = Service.objects.create(name_ar="زرعة", name_en="Implant EK", price=18000, cost=5000,
                                              branch=self.place)
        self.exam = Service.objects.create(name_ar="كشف", name_en="Exam EK", price=500, branch=self.place)
        start = self.today - timedelta(days=30)
        for source, value in ((FeeRule.OWN, 40), (FeeRule.CLINIC, 30)):
            FeeRule.objects.create(dentist=self.surgeon, branch=self.place, method=FeeRule.Method.PERCENT,
                                   value=value, patient_source=source, deduct_costs=True, starts_on=start)

    def bill(self, patient, service, teeth="", paid=None):
        bill = create_bill(patient, [{"service": service, "teeth": teeth}], self.reception, dentist=self.surgeon,
                           branch=self.place)
        PatientPayment.objects.create(patient=patient, bill=bill, branch=self.place,
                                      amount=bill.totals()["net"] if paid is None else paid)
        return bill

    def test_40_percent_of_his_own_patients_and_30_of_the_clinics_after_the_cost(self):
        self.bill(self.own_patient, self.implant, "46")
        self.bill(self.patient, self.implant, "36")
        data = statement(self.surgeon, self.place, self.today, self.today)
        shares = {line["charge"].patient_id: (line["source"], line["share"]) for line in data["lines"]}
        self.assertEqual(shares[self.own_patient.pk], ("own", Decimal("5200.00")))  # 40% of (18000 - 5000)
        self.assertEqual(shares[self.patient.pk], ("clinic", Decimal("3900.00")))  # 30% of (18000 - 5000)
        self.assertEqual(data["costs"], Decimal("10000"))
        quick = totals(self.surgeon, self.place, self.today, self.today)
        self.assertEqual((quick["share"], quick["costs"]), (data["share"], data["costs"]))

    def test_the_cost_is_taken_first_from_a_part_payment(self):
        self.bill(self.patient, self.implant, "36", paid=Decimal("4000"))
        self.assertEqual(statement(self.surgeon, self.place, self.today, self.today)["share"], Decimal("0"))
        self.bill(self.patient, self.exam, paid=Decimal("500"))  # no cost on the examination
        self.assertEqual(statement(self.surgeon, self.place, self.today, self.today)["share"], Decimal("150.00"))

    def test_a_rule_for_one_service_comes_before_the_rules_of_the_patients(self):
        fixed = FeeRule.objects.create(dentist=self.surgeon, branch=self.place, service=self.implant,
                                       method=FeeRule.Method.PER_UNIT, value=2000, starts_on=self.today)
        rules = list(FeeRule.objects.filter(dentist=self.surgeon))
        self.assertEqual(pick_rule(rules, self.implant.pk, self.today, FeeRule.OWN), fixed)
        own = pick_rule(rules, self.exam.pk, self.today, FeeRule.OWN)
        self.assertEqual((own.patient_source, own.value), ("own", 40))
        self.assertEqual(pick_rule(rules, self.exam.pk, self.today, FeeRule.CLINIC).value, 30)

    def test_a_doctor_has_his_own_price_and_the_usual_cost_goes_on_the_bill_line(self):
        DoctorPrice.objects.create(dentist=self.tmj, branch=self.place, service=self.exam, price=1200)
        self.assertEqual(price_and_cost(self.exam, self.tmj, self.place), (Decimal("1200"), Decimal("0")))
        self.assertEqual(price_and_cost(self.exam, self.surgeon, self.place)[0], Decimal("500"))
        self.assertEqual(price_and_cost(self.implant, self.surgeon, self.place, "36, 46")[1], Decimal("10000"))
        bill = create_bill(self.patient, [{"service": self.exam}], self.reception, dentist=self.tmj, branch=self.place)
        self.assertEqual(bill.charges.get().price, Decimal("1200"))
        self.login("khadem")
        page = self.client.get(f"/billing/bills/new/?patient={self.patient.pk}")
        self.assertEqual(page.context["doctor_prices"], {str(self.tmj.pk): {str(self.exam.pk): "1200.00"}})

    def test_the_manager_corrects_the_lab_cost_of_a_line_and_sets_the_prices(self):
        self.bill(self.patient, self.implant, "36")
        charge = Charge.objects.get()
        self.login("amr")
        page = self.client.get(f"/clinics/doctor/{self.surgeon.pk}/?place=PVT")
        self.assertContains(page, "clinic's patient")
        self.assertTrue(page.context["deducts"])
        self.client.post(f"/clinics/cost/{charge.pk}/", {"cost": "6,500", "next": "/"})
        charge.refresh_from_db()
        self.assertEqual(charge.cost, Decimal("6500"))
        response = self.client.post("/clinics/prices/?place=PVT", {"dentist": self.tmj.pk, "service": self.exam.pk,
                                                                   "price": "1100", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DoctorPrice.objects.get().price, Decimal("1100"))
        again = self.client.post("/clinics/prices/?place=PVT", {"dentist": self.tmj.pk, "service": self.exam.pk,
                                                                "price": "900", "is_active": "on"})
        self.assertEqual(again.status_code, 200)  # one price for a doctor and a service
        self.login("khadem")
        self.assertEqual(self.client.post(f"/clinics/cost/{charge.pk}/", {"cost": "1"}).status_code, 403)

    def test_a_cost_is_taken_off_a_percentage_only(self):
        from django.core.exceptions import ValidationError

        rule = FeeRule(dentist=self.tmj, branch=self.place, method=FeeRule.Method.PER_VISIT, value=300,
                       deduct_costs=True)
        with self.assertRaises(ValidationError):
            rule.full_clean()


# ------------------------------------------------------------------ shared rooms
class SharedRoomsTests(KhademMixin, TestCase):
    def book(self, patient, hour, dentist, room=None, minute=0):
        data = {"patient_lookup": patient.file_number, "scheduled_at_0": self.tomorrow.strftime("%d/%m/%Y"),
                "scheduled_at_1": f"{hour:02d}:{minute:02d}", "duration_minutes": 30, "dentist": dentist.pk}
        if room is not None:
            data["room"] = room.pk
        return self.client.post("/schedule/appointments/new/", data)

    def test_any_doctor_books_any_free_room_without_a_room_schedule(self):
        self.login("khadem")
        response = self.book(self.patient, 13, self.tmj)
        self.assertEqual(response.status_code, 302)
        first = Appointment.objects.get()
        self.assertEqual((first.status, first.room), ("scheduled", self.rooms[0]))  # no approval needed
        self.book(self.own_patient, 13, self.endo)
        second = Appointment.objects.exclude(pk=first.pk).get()
        self.assertEqual(second.room, self.rooms[1])  # the first room is taken then

    def test_a_room_holds_one_doctors_patients_at_a_time(self):
        self.login("khadem")
        self.book(self.patient, 13, self.tmj, self.rooms[2])
        response = self.book(self.own_patient, 13, self.endo, self.rooms[2], minute=15)
        self.assertEqual(response.status_code, 200)
        self.assertIn("room", response.context["form"].errors)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_an_appointment_moves_to_another_room_or_swaps_rooms(self):
        one = Appointment.objects.create(branch=self.place, patient=self.patient, scheduled_at=at(self.tomorrow, 14),
                                         duration_minutes=30, dentist=self.tmj, room=self.rooms[0])
        two = Appointment.objects.create(branch=self.place, patient=self.own_patient,
                                         scheduled_at=at(self.tomorrow, 14), duration_minutes=30, dentist=self.endo,
                                         room=self.rooms[1])
        done, _message = change_room(one, self.rooms[1])
        self.assertFalse(done)
        done, _message = change_room(one, self.rooms[1], swap=True)
        self.assertTrue(done)
        two.refresh_from_db()
        self.assertEqual((one.room, two.room), (self.rooms[1], self.rooms[0]))
        self.login("khadem")
        self.client.post(f"/schedule/appointments/{one.pk}/room/", {"room": self.rooms[3].pk})
        one.refresh_from_db()
        self.assertEqual(one.room, self.rooms[3])
        self.login("endo")
        self.assertEqual(self.client.post(f"/schedule/appointments/{one.pk}/room/",
                                          {"room": self.rooms[2].pk}).status_code, 403)

    def test_free_times_look_at_the_free_rooms_and_the_doctors_other_patients(self):
        start = at(self.tomorrow, 0)
        found = free_times(self.place, 30, self.tmj, start=start, days=1)
        self.assertEqual(timezone.localtime(found[0]["at"]).time(), ClinicSettings.get().day_start)  # opening time
        Appointment.objects.create(branch=self.place, patient=self.patient, scheduled_at=found[0]["at"],
                                   duration_minutes=60, dentist=self.tmj, room=self.rooms[0])
        again = free_times(self.place, 30, self.tmj, start=start, days=1)
        self.assertEqual(again[0]["at"], found[0]["at"] + timedelta(hours=1))  # the doctor is busy the first hour
        other = free_times(self.place, 30, self.endo, start=start, days=1)
        self.assertEqual((other[0]["at"], other[0]["room"]), (found[0]["at"], self.rooms[1]))
        Branch.objects.filter(pk=self.place.pk).update(closed_days=str(self.tomorrow.weekday()))
        self.place.refresh_from_db()
        self.assertEqual(free_times(self.place, 30, self.endo, start=start, days=1), [])

    def test_the_day_planner_shows_the_day_by_doctor_with_the_rooms(self):
        Appointment.objects.create(branch=self.place, patient=self.patient, scheduled_at=at(self.today, 15),
                                   dentist=self.tmj, room=self.rooms[2])
        self.login("khadem")
        page = self.client.get("/schedule/day/?by=doctor")
        self.assertEqual([column["doctor"] for column in page.context["columns"]], [self.tmj])
        self.assertContains(page, "room-chip")
        by_room = self.client.get("/schedule/day/")
        self.assertTrue(by_room.context["shared"])
        self.assertContains(by_room, "data-room-choices")
        self.assertTrue(all(slot["open"] for slot in by_room.context["columns"][0]["slots"][:4]))

    def test_the_free_room_takes_the_doctors_own_room_of_the_moment_first(self):
        Appointment.objects.create(branch=self.place, patient=self.patient, scheduled_at=at(self.tomorrow, 16),
                                   duration_minutes=60, dentist=self.tmj, room=self.rooms[3])
        room = free_room(self.place, at(self.tomorrow, 16, 30), at(self.tomorrow, 17), self.tmj.pk)
        self.assertEqual(room, self.rooms[3])


# ------------------------------------------------------------------ referrals and the specialists' charts
class ReferralTests(KhademMixin, TestCase):
    def test_a_referral_goes_to_the_specialist_and_the_reception_books_it(self):
        self.login("amr")
        response = self.client.post(f"/specialists/referrals/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "from_dentist": self.amr.pk, "to_dentist": self.endo.pk, "urgency": "soon",
            "teeth": "36", "reason": "Lingering pain on cold, please treat the canals."})
        referral = Referral.objects.get()
        self.assertRedirects(response, referral.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((referral.specialty, referral.branch, referral.number), ("endodontist", self.place,
                                                                                    f"RF-{referral.pk:06d}"))
        self.assertTrue(Notification.objects.filter(recipient=self.endo_user).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.reception).exists())
        # The reception books it from the letter.
        self.login("khadem")
        page = self.client.get(referral.get_absolute_url())
        self.assertContains(page, "letterhead-elite")  # the letter, in Arabic for the reception
        self.client.post(page.context["book_url"], {
            "patient_lookup": self.patient.file_number, "scheduled_at_0": self.tomorrow.strftime("%d/%m/%Y"),
            "scheduled_at_1": "15:00", "duration_minutes": 60, "dentist": self.endo.pk})
        referral.refresh_from_db()
        self.assertEqual(referral.status, "booked")
        self.assertEqual(referral.appointment.dentist, self.endo)
        self.assertEqual(self.client.post(referral.get_absolute_url(), {"reply": "x"}).status_code, 403)
        # The specialist answers; the referring doctor is told.
        self.login("endo")
        self.client.post(referral.get_absolute_url(), {"reply": "RCT done in two visits."})
        referral.refresh_from_db()
        self.assertEqual((referral.status, referral.replied_by), ("done", self.endo_user))
        self.assertTrue(Notification.objects.filter(recipient=self.amr_user, title__contains="Answer").exists())

    def test_a_referral_outside_the_clinic_needs_a_name_and_the_reception_does_not_refer(self):
        self.login("amr")
        response = self.client.post(f"/specialists/referrals/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "from_dentist": self.amr.pk, "urgency": "routine", "reason": "CBCT"})
        self.assertEqual(response.status_code, 200)
        self.client.post(f"/specialists/referrals/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "from_dentist": self.amr.pk, "urgency": "routine", "reason": "CBCT",
            "to_outside": "Cairo Scan"})
        self.assertEqual(Referral.objects.get().to_name, "Cairo Scan")
        self.login("khadem")
        self.assertEqual(self.client.get(f"/specialists/referrals/new/?patient={self.patient.pk}").status_code, 403)
        self.assertEqual(self.client.get("/specialists/referrals/?show=to_book").status_code, 200)
        self.assertEqual(self.client.get(f"/specialists/patient/{self.patient.pk}/").status_code, 200)

    def test_another_place_does_not_see_the_referrals(self):
        referral = Referral.objects.create(branch=self.place, patient=self.patient, from_dentist=self.amr,
                                           to_dentist=self.endo, reason="x")
        make_user("ciasec", "secretary")
        self.client.login(username="ciasec", password=PASSWORD)
        self.assertEqual(self.client.get(referral.get_absolute_url()).status_code, 403)


class EndoTests(KhademMixin, TestCase):
    def test_an_endodontic_case_with_canals_visits_and_the_chart(self):
        self.login("endo")
        data = {"patient": self.patient.pk, "tooth": "36", "dentist": self.endo.pk, "started_on": "01/09/2026",
                "treatment": "initial", "pain": "moderate", "pain_kinds": ["lingering", "night"],
                "pulpal_diagnosis": "sym_irreversible", "apical_diagnosis": "normal", "difficulty": "moderate",
                "difficulty_factors": ["curvature"], "irrigants": ["naocl_525", "edta"], "rubber_dam": "on",
                "canals-TOTAL_FORMS": "2", "canals-INITIAL_FORMS": "0", "canals-MIN_NUM_FORMS": "0",
                "canals-MAX_NUM_FORMS": "1000",
                "canals-0-name": "MB", "canals-0-working_length": "21.5", "canals-0-master_file": "25/.08",
                "canals-1-name": "D", "canals-1-working_length": "22"}
        response = self.client.post(f"/specialists/endo/new/?patient={self.patient.pk}", data)
        case = EndoCase.objects.get()
        self.assertRedirects(response, case.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((case.tooth, case.branch, case.pain_kinds), (36, self.place, ["lingering", "night"]))
        self.assertEqual(list(case.canals.values_list("name", "working_length")),
                         [("MB", Decimal("21.5")), ("D", Decimal("22.0"))])
        self.client.post(case.get_absolute_url(), {"v-date": "02/09/2026", "v-work": ["access", "medication"],
                                                   "v-medication": "caoh", "v-temporary": "cavit", "v-pain": "6"})
        self.assertEqual(case.visits.get().medication, "caoh")
        page = self.client.get(case.get_absolute_url())
        self.assertContains(page, "canal-bar")
        self.assertContains(page, "Calcium hydroxide")
        # Obturated: the treatment log and the dental chart show the root canal.
        self.client.post(case.get_absolute_url(), {"action": "finish"})
        case.refresh_from_db()
        self.assertEqual(case.status, "obturated")
        step = TreatmentStep.objects.get()
        self.assertEqual((step.teeth, step.operator, case.treatment_step), ("36", self.endo, step))
        self.assertTrue(ToothState.objects.get(patient=self.patient, tooth=36).rct)
        self.client.post(case.get_absolute_url(), {"action": "finish"})
        self.assertEqual(TreatmentStep.objects.count(), 1)  # once only

    def test_the_reception_does_not_open_the_specialists_charts(self):
        case = EndoCase.objects.create(patient=self.patient, branch=self.place, dentist=self.endo, tooth=11)
        self.login("khadem")
        self.assertEqual(self.client.get(case.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get("/specialists/").status_code, 403)

    def test_the_usual_canals_of_each_tooth(self):
        from apps.specialties.views import usual_canals

        self.assertEqual(usual_canals(16), ["MB", "MB2", "DB", "P"])
        self.assertEqual(usual_canals(46), ["MB", "ML", "D"])
        self.assertEqual(usual_canals(14), ["B", "P"])
        self.assertEqual(usual_canals(11), ["Single"])

    def test_an_rct_type_is_used_for_the_chart(self):
        self.assertTrue(TreatmentStepType.objects.filter(chart_effect=ChartEffect.RCT, name_en="Root canal "
                                                                                              "retreatment").exists())


class TMJOrthoShadeTests(KhademMixin, TestCase):
    def test_a_tmj_examination_and_its_follow_up(self):
        self.login("amr")
        response = self.client.post(f"/specialists/tmj/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "exam_date": "05/09/2026", "dentist": self.tmj.pk, "pain_vas": "7",
            "pain_sites": ["joint_l"], "opening": "28", "sound_left": "opening", "muscles": ["masseter_l"],
            "diagnoses": ["dd_nr_limited"], "plan": ["stabilization"]})
        exam = TMJExam.objects.get()
        self.assertRedirects(response, exam.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(exam.opening_limited)
        self.client.post(exam.get_absolute_url(), {"v-date": "20/09/2026", "v-opening": "36", "v-pain_vas": "3",
                                                   "v-done": "Splint delivered"})
        page = self.client.get(exam.get_absolute_url())
        self.assertEqual([row["opening"] for row in page.context["progress"]], [28, 36])
        self.assertContains(page, "Disc displacement without reduction, with limited opening")

    def test_an_orthodontic_case_works_out_the_anb_and_follows_the_wires(self):
        self.login("amr")
        self.client.post(f"/specialists/ortho/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "records_on": "01/06/2026", "dentist": self.amr.pk, "status": "records",
            "symmetric": "on", "molar_right": "II", "overjet": "7", "sna": "83", "snb": "77",
            "anchorage": ["elastics"]})
        case = OrthoCase.objects.get()
        self.assertEqual(case.anb, Decimal("6.0"))
        self.client.post(case.get_absolute_url(), {"v-date": "01/07/2026", "v-upper_wire": "0.014 NiTi",
                                                   "v-lower_wire": "0.014 NiTi", "v-next_weeks": "4"})
        case.refresh_from_db()
        self.assertEqual((case.status, case.bonded_on.isoformat()), ("active", "2026-07-01"))
        page = self.client.get(case.get_absolute_url())
        self.assertEqual(page.context["visit_form"].initial["upper_wire"], "0.014 NiTi")  # the last wires

    def test_the_shade_is_taken_on_the_guide_and_goes_on_the_lab_request(self):
        self.login("amr")
        bad = self.client.post(f"/specialists/shade/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "taken_on": "19/09/2026", "dentist": self.amr.pk, "teeth": "11, 21",
            "guide": "classical", "shade": "2M2", "light": "daylight"})
        self.assertIn("shade", bad.context["form"].errors)
        page = self.client.get(f"/specialists/shade/new/?patient={self.patient.pk}")
        self.assertContains(page, 'id="shade-guides"')
        self.client.post(f"/specialists/shade/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "taken_on": "19/09/2026", "dentist": self.amr.pk, "teeth": "11 21",
            "guide": "classical", "shade": "A2", "shade_cervical": "A3", "shade_incisal": "A1", "stump": "ND2",
            "characters": ["halo"], "light": "daylight", "prosthesis": "Zirconia crowns"})
        record = ShadeRecord.objects.get()
        self.assertEqual((record.teeth, record.stump), ("11, 21", "ND2"))
        form = self.client.get(f"/clinical/lab/new/?patient={self.patient.pk}&shade_record={record.pk}").context["form"]
        self.assertEqual((form.initial["shade"], form.initial["stump_shade"], form.initial["teeth"]),
                         ("A2", "ND2", "11, 21"))


class Round15ProsthoTests(KhademMixin, TestCase):
    """Round 15: the prosthodontist has a real chart (the shade is one step of it)."""

    def test_the_prosthodontic_chart_and_its_page(self):
        from apps.specialties.models import ProsthoCase

        self.login("amr")
        tiles = self.client.get(f"/specialists/patient/{self.patient.pk}/")
        self.assertContains(tiles, "Prosthodontic chart")
        response = self.client.post(f"/specialists/prostho/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "examined_on": "01/09/2026", "dentist": self.amr.pk, "status": "examined",
            "upper": "III", "lower": "none", "missing_teeth": "15, 16", "abutment_teeth": "14 17",
            "abutment_findings": ["rct"], "vertical_dimension": "normal", "scheme": "canine",
            "parafunction": ["bruxism"], "smile_line": "medium", "plan": "bridge", "plan_teeth": "14-17",
            "material": "zirconia", "retention": "cemented"})
        case = ProsthoCase.objects.get()
        self.assertRedirects(response, case.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((case.missing_teeth, case.abutment_teeth, case.abutment_findings),
                         ("16, 15", "17, 14", ["rct"]))  # in the order of the chart
        page = self.client.get(case.get_absolute_url())
        self.assertContains(page, "Bridge on teeth")
        self.assertContains(page, "Bruxism")
        self.assertContains(self.client.get("/specialists/?kind=prostho"), "Bridge on teeth")


# ------------------------------------------------------------------ the printed plan and lab request
class PrintTests(KhademMixin, TestCase):
    def test_the_treatment_plan_for_the_patient_with_the_team_and_the_fees(self):
        types = {t.name_en: t for t in TreatmentStepType.objects.all()}
        plan = TreatmentPlan.objects.create(patient=self.patient, dentist=self.amr, comprehensive=True,
                                            diagnosis="Irreversible pulpitis of 36", duration="5 months")
        PlanItem.objects.create(plan=plan, phase=2, step_type=types["Root canal treatment"], teeth="36",
                                dentist=self.endo, fee=4000)
        PlanItem.objects.create(plan=plan, phase=3, step_type=types["Implant placement"], teeth="46",
                                dentist=self.amr, fee=18000)
        self.login("amr")
        page = self.client.get(f"/chart/plan/{plan.pk}/print/?lang=en")
        self.assertContains(page, "Your treatment team")
        self.assertContains(page, "22,000.00")
        self.assertContains(page, "El Khadem Dental Clinic")
        self.assertEqual([member["doctor"] for member in page.context["team"]], [self.amr, self.endo])
        arabic = self.client.get(f"/chart/plan/{plan.pk}/print/?lang=ar")
        self.assertContains(arabic, 'dir="rtl"')
        self.assertContains(arabic, types["Root canal treatment"].name_ar)
        # The plan form offers the doctor and the fee of each item.
        form = self.client.get(f"/chart/plan/{plan.pk}/edit/").context["formset"].forms[0]
        self.assertIn("dentist", form.fields)
        self.assertIn(self.endo, form.fields["dentist"].queryset)

    def test_the_detailed_lab_request_and_its_print(self):
        lab, work = Lab.objects.first(), LabWorkType.objects.get(name_en="Zirconia crown")
        self.login("amr")
        response = self.client.post(f"/clinical/lab/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "patient_lookup": self.patient.file_number, "dentist": self.amr.pk,
            "lab": lab.pk, "work_type": work.pk, "stage": "bisque", "teeth": "11, 21", "units": 2,
            "shade_guide": "classical", "shade": "A2", "shade_cervical": "3M2", "margin": "chamfer",
            "enclosures": ["impression", "bite"]})
        self.assertEqual(response.status_code, 200)  # a 3D-Master tab on a VITA classical request
        self.client.post(f"/clinical/lab/new/?patient={self.patient.pk}", {
            "patient": self.patient.pk, "patient_lookup": self.patient.file_number, "dentist": self.amr.pk,
            "lab": lab.pk, "work_type": work.pk, "stage": "bisque", "teeth": "11, 21", "units": 2,
            "shade_guide": "classical", "shade": "A2", "shade_cervical": "A3", "stump_shade": "ND2",
            "margin": "chamfer", "enclosures": ["impression", "bite"]})
        request = LabRequest.objects.get()
        self.assertEqual((request.stage, request.enclosures, request.branch), ("bisque", ["impression", "bite"],
                                                                               self.place))
        page = self.client.get(f"/clinical/lab/{request.pk}/print/")
        self.assertContains(page, "Bisque try-in")
        self.assertContains(page, "bi-check-square-fill", count=2)
        self.assertEqual([tooth for tooth, on in page.context["upper"] if on], [11, 21])
        self.assertContains(page, "letterhead-elite")


class DemoDataTests(TestCase):
    def test_the_practice_copy_has_el_khadem(self):
        from io import StringIO

        from django.core.management import call_command

        call_command("load_demo_data", password="demo12345", stdout=StringIO())
        place = Branch.objects.get(code="PVT")
        self.assertEqual(Patient.objects.filter(branch=place).count(), 8)
        self.assertTrue(EndoCase.objects.filter(status="obturated").exists())
        self.assertTrue(Referral.objects.filter(status="done").exists())
        self.assertTrue(EndoCanal.objects.exists())
        surgeon = Dentist.objects.get(full_name="Dr. Tarek Nour")
        data = totals(surgeon, place, timezone.localdate() - timedelta(days=60), timezone.localdate())
        self.assertGreater(data["share"], 0)
        self.assertGreater(data["costs"], 0)
