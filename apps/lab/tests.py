"""The dental lab: cases from our places and outside clinics with their own prices, the steps and their times, the
people, remakes, other labs, blocks, receipts, WhatsApp answers, the report; the login page with the places; the
dashboard and the Back link."""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.clinical.models import Lab, LabRequest, LabWorkType
from apps.clinical.services import perform_lab_action
from apps.core.models import Branch, Notification, UserProfile
from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic
from apps.dentists.models import Dentist
from apps.lab import services
from apps.lab.models import (
    LabBlock, LabCase, LabCaseItem, LabCaseStep, LabClient, LabMessage, LabOutsource, LabPayment,
    LabPrice, LabPriceList, LabSettings, LabWorker, Step,
)
from apps.lab.stats import board_counts, report
from apps.lab.whatsapp import answer_for, cases_for, status_text
from apps.stock.models import StockCategory, StockItem, StockMovement
from apps.stock.services import record_movement


class LabMixin:
    def setUp(self):
        self.cia = setup_clinic()
        self.lab_place = Branch.objects.get(code="LAB")
        self.head = self.lab_person("head", "lab_head")
        self.manager = self.lab_person("manager", "lab_manager")
        self.secretary = self.lab_person("labsec", "lab_secretary")
        self.designer_user = make_user("designer", "dentist", "lab_designer")
        self.designers = [LabWorker.objects.create(name="Dr. Sherif", user=self.designer_user, jobs=[Step.DESIGN],
                                                   fee_per_unit=Decimal("150")),
                          LabWorker.objects.create(name="Dr. Nada", jobs=[Step.DESIGN])]
        self.miller = LabWorker.objects.create(name="Mahmoud", jobs=[Step.MILLING, Step.SINTERING])
        self.ceramist = LabWorker.objects.create(name="Ayman", jobs=[Step.STAIN_GLAZE])
        self.checker = LabWorker.objects.create(name="Dr. Hossam", user=self.head, jobs=[Step.QC])
        self.zirconia = LabWorkType.objects.get(name_en="Zirconia crown")
        self.denture = LabWorkType.objects.get(name_en="Complete denture")
        self.outside_list = LabPriceList.objects.create(name="Outside clinics")
        LabPrice.objects.create(price_list=self.outside_list, work_type=self.zirconia, price=Decimal("1800"))
        self.clinic = LabClient.objects.create(name="Smile Center", price_list=self.outside_list,
                                               contact="Dr. Heba", phone="01223334445")

    def lab_person(self, username, *roles):
        user = make_user(username, *roles)
        UserProfile.objects.update_or_create(user=user, defaults={"branch": self.lab_place})
        return user

    def new_case(self, client=None, work=None, units=2, **fields):
        case = LabCase.objects.create(client=client or self.clinic, doctor="Dr. Heba", doctor_phone="01223334445",
                                      patient_name="Karim", created_by=self.secretary, **fields)
        LabCaseItem.objects.create(case=case, work_type=work or self.zirconia, teeth="11 21", units=units)
        return services.start_case(case, self.secretary)


class CaseTests(LabMixin, TestCase):
    def test_a_case_received_takes_its_steps_price_and_date(self):
        case = self.new_case()
        self.assertTrue(case.number.startswith("LAB-"))
        self.assertEqual(case.step, Step.RECEIVED)
        self.assertEqual(case.route, ["received", "design", "milling", "sintering", "stain_glaze", "qc", "ready"])
        self.assertEqual(case.total, Decimal("3600"))  # 2 × 1,800 of the client's list
        self.assertEqual(case.due_date, timezone.localdate() + timedelta(days=7))  # the usual days of the work
        # The managers are told there is a case to give out.
        self.assertTrue(Notification.objects.filter(recipient=self.manager, url=case.get_absolute_url()).exists())

    def test_a_conventional_impression_is_poured_and_scanned_before_the_design(self):
        case = LabCase.objects.create(client=self.clinic, impression=LabCase.Impression.CONVENTIONAL)
        LabCaseItem.objects.create(case=case, work_type=self.zirconia, units=1)
        services.start_case(case, self.secretary)
        self.assertEqual(case.route[:3], ["received", "models", "design"])
        denture = self.new_case(work=self.denture, units=1)
        self.assertEqual(denture.route, ["received", "models", "setup", "processing", "finishing", "qc", "ready"])

    def test_the_steps_go_on_with_their_people_and_times(self):
        case = self.new_case()
        start = timezone.now() - timedelta(hours=30)
        LabCaseStep.objects.filter(case=case).update(started_at=start)
        services.move(case, Step.DESIGN, self.manager, worker=self.designers[0], now=start + timedelta(hours=1))
        # The designer (a CIA doctor with a login) is told.
        self.assertTrue(Notification.objects.filter(recipient=self.designer_user).exists())
        self.assertEqual(services.next_step(case), Step.MILLING)
        services.move(case, Step.MILLING, self.designer_user, now=start + timedelta(hours=9))
        self.assertEqual(case.worker, self.miller)  # the only person who mills: given to him by itself
        services.move(case, Step.SINTERING, self.manager, now=start + timedelta(hours=12))
        design = case.steps.get(step=Step.DESIGN)
        self.assertEqual(design.worker, self.designers[0])
        self.assertAlmostEqual(design.hours, 8)
        # On hold during the sintering: going on resumes the sintering, not the step after it.
        services.move(case, Step.ON_HOLD, self.manager, notes="Waiting for the doctor")
        self.assertEqual(services.next_step(case), Step.SINTERING)
        services.move(case, Step.SINTERING, self.manager)
        # A try-in after the stain and glaze: coming back goes on to the check.
        services.move(case, Step.STAIN_GLAZE, self.manager)
        services.move(case, Step.TRY_IN, self.secretary)
        self.assertEqual(services.next_step(case), Step.QC)
        services.move(case, Step.QC, self.secretary)
        services.move(case, Step.READY, self.head)
        self.assertEqual(services.next_step(case), Step.DELIVERED)
        services.move(case, Step.DELIVERED, self.secretary)
        self.assertIsNotNone(case.delivered_at)
        self.assertFalse(case.is_open)
        self.assertIsNone(services.next_step(case))

    def test_who_may_move_a_case(self):
        case = self.new_case()
        services.move(case, Step.DESIGN, self.manager, worker=self.designers[1])
        self.client.login(username="designer", password=PASSWORD)
        # Not his case: refused.
        self.assertEqual(self.client.post(f"/lab/cases/{case.pk}/move/", {"to_step": "milling"}).status_code, 403)
        services.assign(case, self.designers[0], self.manager)
        response = self.client.post(f"/lab/cases/{case.pk}/move/", {"to_step": "milling"})
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.step, Step.MILLING)
        # He cannot jump to another step, nor open the money pages.
        self.assertEqual(self.client.post(f"/lab/cases/{case.pk}/move/", {"to_step": "ready"}).status_code, 403)
        for url in ("/lab/clients/", "/lab/prices/", "/lab/receipts/", "/lab/report/", "/lab/cases/new/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/lab/mine/").status_code, 200)
        # The secretary delivers what is ready, but does not give out the work.
        services.move(case, Step.READY, self.manager)
        self.client.login(username="labsec", password=PASSWORD)
        self.assertEqual(self.client.post(f"/lab/cases/{case.pk}/assign/", {"worker": self.miller.pk}).status_code,
                         403)
        self.client.post(f"/lab/cases/{case.pk}/move/", {"to_step": "delivered"})
        case.refresh_from_db()
        self.assertEqual(case.step, Step.DELIVERED)

    def test_the_lab_staff_and_the_clinics_see_their_own_pages(self):
        case = self.new_case()
        self.client.login(username="labsec", password=PASSWORD)
        for url in ("/", "/lab/", "/lab/cases/", f"/lab/cases/{case.pk}/", f"/lab/cases/{case.pk}/label/",
                    f"/lab/cases/{case.pk}/print/", "/lab/cases/new/", "/lab/incoming/", "/lab/blocks/",
                    "/lab/clients/", f"/lab/clients/{self.clinic.pk}/", f"/lab/clients/{self.clinic.pk}/statement/",
                    "/lab/receipts/", "/lab/receipts/new/", "/lab/whatsapp/", "/lab/request-form/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/patients/").status_code, 403)  # no patients' files at the lab
        home = self.client.get("/")
        self.assertEqual(home.context["current_branch"], self.lab_place)
        self.assertContains(home, 'href="/lab/cases/new/"')  # receive a case
        self.client.login(username="head", password=PASSWORD)
        for url in ("/lab/prices/", "/lab/report/", "/lab/staff/", "/lab/settings/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/lab/").status_code, 403)

    def test_receiving_a_case_on_the_page_with_its_work_and_prices(self):
        self.client.login(username="labsec", password=PASSWORD)
        data = {"client": self.clinic.pk, "doctor": "Dr. Heba", "doctor_phone": "01223334445",
                "patient_name": "Omar", "impression": "digital", "stage": "final", "shade": "A2",
                "enclosures": ["scan"],
                "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000", "items-0-work_type": self.zirconia.pk, "items-0-teeth": "36",
                "items-0-units": "1", "items-0-material": "", "items-0-unit_price": ""}
        response = self.client.post("/lab/cases/new/", data)
        case = LabCase.objects.get(patient_name="Omar")
        self.assertRedirects(response, f"{case.get_absolute_url()}?new=1")
        self.assertEqual(case.total, Decimal("1800"))
        self.assertEqual(case.received_by.username, "labsec")
        page = self.client.get(response.url)
        self.assertContains(page, f"/lab/cases/{case.pk}/label/")  # print the label
        self.assertContains(page, f"/lab/cases/{case.pk}/whatsapp/received/")  # tell the doctor

    def test_a_remake_is_linked_and_free_when_the_lab_is_at_fault(self):
        case = self.new_case()
        free = services.make_remake(case, self.secretary, LabCase.RemakeReason.SHADE, LabCase.Fault.LAB, "Too light")
        self.assertEqual(free.remake_of, case)
        self.assertEqual(free.total, Decimal("0"))
        self.assertTrue(free.urgent)
        paid = services.make_remake(case, self.secretary, LabCase.RemakeReason.IMPRESSION, LabCase.Fault.CLINIC,
                                    "Distorted", in_hand=False)
        self.assertEqual(paid.total, Decimal("3600"))
        self.assertEqual(paid.step, Step.INCOMING)
        self.assertEqual(case.remakes.count(), 2)

    def test_work_sent_to_another_lab(self):
        case = self.new_case()
        other = Lab.objects.create(name="Alpha")
        sent = services.outsource(case, other, "Titanium printing", self.manager, cost=Decimal("6000"))
        self.assertEqual(case.step, Step.OUTSOURCED)
        services.outsource_back(sent, self.secretary)
        case.refresh_from_db()
        self.assertEqual(case.step, Step.DESIGN)  # the step after the last one finished
        self.assertIsNotNone(LabOutsource.objects.get().back_at)


class FromOurClinicsTests(LabMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.our_lab = Lab.objects.get(branch=self.lab_place)
        self.reception = make_user("sec", "secretary")
        self.dentist = Dentist.objects.create(full_name="Dr. Mona", phone="01000000006", user=make_user("mona",
                                                                                                        "dentist"))
        self.patient = make_patient(self.cia)
        self.request = LabRequest.objects.create(
            branch=self.cia, patient=self.patient, lab=self.our_lab, work_type=self.zirconia, teeth="36", units=1,
            dentist=self.dentist, shade="A2", shade_cervical="A3", status=LabRequest.Status.APPROVED,
            work_form=LabRequest.WorkForm.DIGITAL, created_by=self.reception)

    def test_a_request_sent_to_our_lab_waits_there_and_comes_back(self):
        perform_lab_action(self.request, "send", self.reception, checked=True)
        case = LabCase.objects.get(request=self.request)
        self.assertEqual(case.step, Step.INCOMING)
        self.assertEqual(case.client.branch, self.cia)
        self.assertEqual(case.doctor, "Dr. Mona")
        self.assertEqual(case.patient_name, self.patient.full_name)
        self.assertIn("A2", case.shade)
        self.assertIn("A3", case.shade)
        # The lab's secretary checks it in.
        self.client.login(username="labsec", password=PASSWORD)
        self.assertContains(self.client.get("/lab/incoming/"), case.number)
        self.client.post(f"/lab/cases/{case.pk}/receive/", {"checked": "on", "enclosures": ["scan"]})
        case.refresh_from_db()
        self.assertEqual(case.step, Step.RECEIVED)
        # The clinic sees where its work is.
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get(self.request.get_absolute_url())
        self.assertContains(page, case.number)
        self.assertContains(page, "lab-step-chip step-received")
        # Delivered by the lab: the clinic's reception is told; checked in at the clinic.
        services.move(case, Step.DELIVERED, self.manager)
        self.assertTrue(Notification.objects.filter(recipient=self.reception, url=self.request.get_absolute_url())
                        .exists())
        perform_lab_action(self.request, "receive", self.reception, checked=True)
        # The work comes back for a remake: a new case on its way, linked to the first.
        perform_lab_action(self.request, "remake", self.reception, notes="Open margin")
        remake = LabCase.objects.get(remake_of=case)
        self.assertEqual(remake.step, Step.INCOMING)
        self.assertIn("Open margin", remake.instructions)

    def test_the_clinic_receiving_closes_a_case_the_lab_forgot(self):
        perform_lab_action(self.request, "send", self.reception, checked=True)
        perform_lab_action(self.request, "receive", self.reception, checked=True)
        self.assertEqual(LabCase.objects.get(request=self.request).step, Step.DELIVERED)

    def test_the_lab_price_of_our_place_becomes_the_lab_cost_of_the_request(self):
        client = services.client_for_place(self.cia)
        LabPrice.objects.create(price_list=client.price_list, work_type=self.zirconia, price=Decimal("1200"))
        perform_lab_action(self.request, "send", self.reception, checked=True)
        self.request.refresh_from_db()
        self.assertEqual(self.request.lab_cost, Decimal("1200"))
        self.assertEqual(LabCase.objects.get(request=self.request).total, Decimal("1200"))


class BlocksAndMoneyTests(LabMixin, TestCase):
    def test_a_block_counts_the_units_made_from_it(self):
        category = StockCategory.objects.get(name_en="Lab blocks and discs")
        self.assertTrue(category.lab_blocks)
        disc = StockItem.objects.create(name="Zirconia disc 98×14", category=category, branch=self.lab_place,
                                        unit="disc", unit_cost=Decimal("4200"))
        record_movement(disc, StockMovement.Kind.IN, 3, self.manager, branch=self.lab_place)
        block = services.open_block(disc, self.manager, lot="ZR1")
        disc.refresh_from_db()
        self.assertEqual(disc.quantity, 2)  # one disc out of the lab's stock
        self.assertEqual(StockMovement.objects.filter(kind="out").get().branch, self.lab_place)
        first, second = self.new_case(units=3), self.new_case(units=2)
        services.use_block(block, first, 3, self.manager)
        self.client.login(username="manager", password=PASSWORD)
        self.client.post(f"/lab/cases/{second.pk}/block/", {"block": block.pk, "units": 2})
        self.assertEqual(services.block_units()[block.pk], 5)
        self.assertContains(self.client.get(block.get_absolute_url()), second.number)
        self.client.post(f"/lab/blocks/{block.pk}/finish/", {"status": "finished"})
        block.refresh_from_db()
        self.assertEqual(block.status, LabBlock.Status.FINISHED)
        with self.assertRaises(Exception):
            services.use_block(block, first, 1, self.manager)
        rows = report(timezone.localdate(), timezone.localdate())["block_kinds"]
        self.assertEqual(rows[0]["average"], 5)
        self.assertEqual(rows[0]["cost_per_unit"], Decimal("840"))

    def test_the_account_of_a_client_and_its_receipts(self):
        case = self.new_case()
        services.move(case, Step.DELIVERED, self.manager)
        self.new_case()  # still in the lab
        self.client.login(username="labsec", password=PASSWORD)
        self.assertEqual(self.client.get(f"/lab/receipts/new/?client={self.clinic.pk}").context["form"]
                         .initial["amount"], Decimal("3600"))
        self.client.post("/lab/receipts/new/", {"client": self.clinic.pk, "amount": "2000", "method": "cash",
                                                "paid_on": timezone.localdate().strftime("%d/%m/%Y")})
        money = services.balances([self.clinic])[self.clinic.pk]
        self.assertEqual((money["billed"], money["paid"], money["balance"], money["in_work"]),
                         (Decimal("3600"), Decimal("2000"), Decimal("1600"), Decimal("3600")))
        payment = LabPayment.objects.get()
        # The secretary cannot cancel; the head cancels with a reason and it is kept.
        self.assertEqual(self.client.post(f"/lab/receipts/{payment.pk}/cancel/", {"reason": "x"}).status_code, 403)
        self.client.login(username="head", password=PASSWORD)
        self.client.post(f"/lab/receipts/{payment.pk}/cancel/", {"reason": "Written twice"})
        payment.refresh_from_db()
        self.assertTrue(payment.is_cancelled)
        self.assertEqual(services.balances([self.clinic])[self.clinic.pk]["balance"], Decimal("3600"))
        page = self.client.get(f"/lab/clients/{self.clinic.pk}/statement/")
        self.assertEqual(page.context["closing"], Decimal("3600"))

    def test_the_prices_of_each_list(self):
        self.client.login(username="head", password=PASSWORD)
        cia_list = services.client_for_place(Branch.objects.get(code="CIA")).price_list
        self.client.post("/lab/prices/", {f"p-{cia_list.pk}-{self.zirconia.pk}": "1,200",
                                          f"p-{self.outside_list.pk}-{self.zirconia.pk}": ""})
        self.assertEqual(LabPrice.objects.get(price_list=cia_list).price, Decimal("1200"))
        self.assertFalse(LabPrice.objects.filter(price_list=self.outside_list).exists())
        self.client.login(username="manager", password=PASSWORD)
        self.assertEqual(self.client.get("/lab/prices/").status_code, 403)


class WhatsAppTests(LabMixin, TestCase):
    def test_the_answer_says_the_real_status(self):
        case = self.new_case()
        services.move(case, Step.DESIGN, self.manager)
        text = status_text(case)
        self.assertIn(case.number, text)
        self.assertIn("التصميم", text)
        self.assertEqual(list(cases_for(str(case.pk))), [case])
        self.assertEqual(list(cases_for(case.number)), [case])
        self.assertEqual(list(cases_for("01223334445")), [case])
        # By itself it answers only the doctor or the client of the case.
        self.assertEqual(answer_for(case.number, "+201223334445")[1], [case])
        self.assertEqual(answer_for(case.number, "+201000000000")[1], [])
        self.assertEqual(answer_for("hello", "+201223334445")[1], [])

    def test_one_click_answer_is_kept(self):
        case = self.new_case()
        self.client.login(username="labsec", password=PASSWORD)
        response = self.client.post(f"/lab/whatsapp/answer/{case.pk}/", {"phone": ""})
        self.assertTrue(response.url.startswith("https://wa.me/201223334445?text="))
        self.assertEqual(LabMessage.objects.get().kind, LabMessage.Kind.STATUS)
        self.assertContains(self.client.get(f"/lab/whatsapp/?q={case.pk}"), case.number)
        response = self.client.post(f"/lab/cases/{case.pk}/whatsapp/received/")
        self.assertTrue(response.url.startswith("https://wa.me/"))

    def test_the_automatic_answer_checks_it_comes_from_whatsapp(self):
        case = self.new_case()
        options = LabSettings.get()
        options.auto_reply, options.wa_verify_token, options.wa_app_secret = True, "word", "secret"
        options.wa_phone_number_id, options.wa_token = "123", "token"
        options.save()
        self.assertEqual(self.client.get("/lab/whatsapp/hook/?hub.mode=subscribe&hub.verify_token=word"
                                         "&hub.challenge=42").content, b"42")
        self.assertEqual(self.client.get("/lab/whatsapp/hook/?hub.mode=subscribe&hub.verify_token=no").status_code,
                         403)
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
            {"from": "201223334445", "type": "text", "text": {"body": f"where is {case.number}?"}}]}}]}]}).encode()
        self.assertEqual(self.client.post("/lab/whatsapp/hook/", body, content_type="application/json",
                                          HTTP_X_HUB_SIGNATURE_256="sha256=wrong").status_code, 403)
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        with mock.patch("apps.lab.whatsapp.send", return_value=True) as send:
            response = self.client.post("/lab/whatsapp/hook/", body, content_type="application/json",
                                        HTTP_X_HUB_SIGNATURE_256=signature)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_args[0][1], "201223334445")
        self.assertIn(case.number, send.call_args[0][2])
        self.assertEqual(LabMessage.objects.get(kind=LabMessage.Kind.AUTO).case, case)


class ReportTests(LabMixin, TestCase):
    def test_the_report_counts_steps_people_remakes_and_money(self):
        start = timezone.now() - timedelta(days=2)
        case = self.new_case()
        LabCaseStep.objects.filter(case=case).update(started_at=start)
        LabCase.objects.filter(pk=case.pk).update(received_at=start)
        case.refresh_from_db()
        services.move(case, Step.DESIGN, self.manager, worker=self.designers[0], now=start + timedelta(hours=2))
        services.move(case, Step.MILLING, self.manager, now=start + timedelta(hours=6))
        services.move(case, Step.DELIVERED, self.secretary, now=start + timedelta(hours=30))
        services.make_remake(case, self.secretary, LabCase.RemakeReason.FIT, LabCase.Fault.LAB, "Open margin")
        today = timezone.localdate()
        data = report(today - timedelta(days=5), today)
        design = next(row for row in data["steps"] if row["step"] == Step.DESIGN)
        self.assertEqual((design["count"], design["average"]), (1, 4))
        self.assertEqual(data["delivered"], 1)
        self.assertEqual(data["remakes"], 1)
        self.assertEqual(data["remake_rate"], 100)
        sherif = next(row for row in data["staff"] if row["worker"] == self.designers[0])
        self.assertEqual((sherif["designed"], sherif["fee"], sherif["remakes"]), (2, Decimal("300"), 1))
        self.assertEqual(data["billed"], Decimal("3600"))
        self.assertEqual(board_counts()[Step.RECEIVED], 1)  # the remake waits to start
        self.client.login(username="manager", password=PASSWORD)
        page = self.client.get("/lab/report/")
        self.assertFalse(page.context["with_money"])
        self.assertNotContains(page, "Left for the lab")
        self.client.login(username="head", password=PASSWORD)
        self.assertContains(self.client.get("/lab/report/"), "Left for the lab")


class LoginPlacesTests(TestCase):
    def setUp(self):
        self.cia = setup_clinic()
        self.lab = Branch.objects.get(code="LAB")

    def test_the_login_page_offers_the_four_places(self):
        page = self.client.get("/login/")
        self.assertEqual([p.code for p in page.context["login_places"]], ["CIA", "PVT", "CIC", "LAB"])
        self.assertContains(page, "?place=LAB")
        page = self.client.get("/login/?place=LAB")
        self.assertContains(page, "login-page place-LAB")
        self.assertContains(page, 'name="place" value="LAB"')

    def test_the_place_chosen_opens_after_login(self):
        worker = make_user("labsec", "lab_secretary")
        UserProfile.objects.update_or_create(user=worker, defaults={"branch": self.lab})
        self.client.post("/login/?place=LAB", {"username": "labsec", "password": PASSWORD, "place": "LAB"})
        self.assertEqual(self.client.get("/").context["current_branch"], self.lab)
        # Someone who does not work at the place chosen opens her own place, and is told.
        make_user("sec", "secretary")
        self.client.logout()
        response = self.client.post("/login/", {"username": "sec", "password": PASSWORD, "place": "LAB"},
                                    follow=True)
        self.assertEqual(response.context["current_branch"], self.cia)
        self.assertEqual(len(list(response.context["messages"])), 1)  # "you do not work at the lab"
        # The owner can switch to the lab from the top bar.
        make_user("boss", "owner")
        self.client.login(username="boss", password=PASSWORD)
        self.assertIn(self.lab, self.client.get("/").context["working_places"])
        self.client.post("/place/", {"place": "LAB", "next": "/"})
        self.assertEqual(self.client.get("/").context["current_branch"], self.lab)


class DashboardAndBackTests(TestCase):
    def setUp(self):
        self.cia = setup_clinic()

    def test_the_dashboard_shows_the_places_and_money_to_those_who_may(self):
        make_user("boss", "owner")
        make_user("head", "head_cia")
        make_user("sec", "secretary")
        self.client.login(username="boss", password=PASSWORD)
        page = self.client.get("/dashboard/?period=week")
        self.assertTrue(page.context["money"])
        self.assertEqual({row["place"].code for row in page.context["rows"]}, {"CIA", "PVT", "CIC"})
        self.assertIn("lab", page.context)
        self.assertEqual(len(page.context["charts"]), 2)
        self.client.login(username="head", password=PASSWORD)
        page = self.client.get("/dashboard/?period=month")
        self.assertFalse(page.context["money"])
        self.assertNotContains(page, "Paid by the patients")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/dashboard/").status_code, 403)

    def test_back_opens_the_page_above(self):
        from apps.core.navigation import up_url

        self.assertEqual(up_url("/lab/clients/5/edit/"), "/lab/clients/5/")
        self.assertEqual(up_url("/lab/cases/44/"), "/lab/cases/")
        self.assertEqual(up_url("/patients/12/"), "/patients/")
        self.assertEqual(up_url("/lab/"), "/")
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertContains(self.client.get("/patients/new/"), 'href="/patients/" data-up')
        self.assertContains(self.client.get("/"), 'data-saving-text=')

    def test_the_owner_gives_a_person_the_lab(self):
        make_user("boss", "owner")
        self.client.login(username="boss", password=PASSWORD)
        lab = Branch.objects.get(code="LAB")
        data = {"username": "nora", "first_name": "Nora", "roles": ["lab_secretary"], "places": [lab.pk],
                "is_active": "on"}
        self.client.post("/settings/users/new/", data)
        self.assertEqual(UserProfile.objects.get(user__username="nora").branch, lab)
        data.update(username="mona2", roles=["secretary"])
        page = self.client.post("/settings/users/new/", data)
        self.assertFalse(UserProfile.objects.filter(user__username="mona2").exists())
        self.assertIn("places", page.context["form"].errors)


class Round14LabDayTests(LabMixin, TestCase):
    """The end of the day at the lab is the lab's own: its receipts, the work delivered, the cash counted (before,
    the page opened at the lab showed CIA's day)."""

    def test_the_lab_closes_its_own_day(self):
        from apps.billing.models import DayClosing, PatientPayment

        LabPayment.objects.create(client=self.clinic, amount=Decimal("900"), method="cash", received_by=self.secretary)
        LabPayment.objects.create(client=self.clinic, amount=Decimal("300"), method="bank",
                                  received_by=self.secretary)
        cancelled = LabPayment.objects.create(client=self.clinic, amount=Decimal("50"), received_by=self.secretary)
        cancelled.cancelled_at = timezone.now()
        cancelled.save()
        PatientPayment.objects.create(patient=make_patient(self.cia), amount=Decimal("700"))  # CIA's, not the lab's
        self.client.login(username="labsec", password=PASSWORD)
        page = self.client.get("/lab/day/")
        summary = page.context["summary"]
        self.assertEqual((summary["total"], summary["cash"], summary["count"], len(summary["cancelled"])),
                         (Decimal("1200"), Decimal("900"), 2, 1))
        self.assertFalse(page.context["reviewer"])
        self.client.post("/lab/day/", {"action": "close", "cash_counted": "880"})
        closing = DayClosing.objects.get(branch=self.lab_place)
        self.assertEqual((closing.cash_expected, closing.difference), (Decimal("900"), Decimal("-20")))
        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)
        self.client.post("/place/", {"place": "LAB", "next": "/"})
        self.assertRedirects(self.client.get("/billing/day/"), "/lab/day/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/billing/month/?month=2026-10"), "/lab/day/month/?month=2026-10",
                             fetch_redirect_response=False)
        owner_page = self.client.get("/lab/day/")
        self.assertTrue(owner_page.context["reviewer"])
        self.client.post("/lab/day/", {"action": "review", "review_notes": "20 short"})
        closing.refresh_from_db()
        self.assertEqual(closing.review_notes, "20 short")
        month = self.client.get("/lab/day/month/")
        self.assertEqual(month.context["rows"][0]["total"], Decimal("1200"))
        self.assertContains(month, "/lab/day/?day=")
