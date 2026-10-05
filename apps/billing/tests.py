from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Charge, PatientPayment, Service, account
from apps.core.testing import PASSWORD, make_patient, make_user, setup_clinic


class PatientPaymentTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.cbct = Service.objects.get(name_en="CBCT")
        self.cbct.price = Decimal("1200")
        self.cbct.save()
        self.consult = Service.objects.get(name_en="Consultation")
        self.url = f"/billing/patient/{self.patient.pk}/"

    def add(self, service, **extra):
        return self.client.post(self.url, {"action": "charge", "c-service": service.pk,
                                           "c-charged_on": "01/09/2026", **extra})

    def test_services_discounts_and_part_payments(self):
        self.add(self.consult, **{"c-price": "300", "c-discount_percent": "100", "c-discount_reason": "Academy case"})
        self.add(self.cbct)  # the price comes from the list
        cbct = Charge.objects.get(service=self.cbct)
        self.assertEqual((cbct.price, cbct.net), (Decimal("1200"), Decimal("1200")))
        self.assertEqual(account(self.patient)["balance"], Decimal("1200"))  # the consultation was free
        # A discount needs a reason.
        response = self.add(self.cbct, **{"c-discount_percent": "50"})
        self.assertIn("discount_reason", response.context["charge_form"].errors)
        # Part of the CBCT now, the rest later; the receipt shows what is left.
        response = self.client.post(self.url, {"action": "payment", "p-charge": cbct.pk, "p-amount": "700",
                                               "p-paid_on": "02/09/2026", "p-method": "cash"})
        payment = PatientPayment.objects.get()
        self.assertRedirects(response, payment.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(payment.receipt_number, f"PR-{payment.pk:06d}")
        self.assertContains(self.client.get(payment.get_absolute_url()), "500")
        state = account(self.patient)
        self.assertEqual([(row["paid"], row["left"]) for row in state["rows"]],
                         [(Decimal("0"), Decimal("0")), (Decimal("700"), Decimal("500"))])
        # No paying more than what is owed.
        response = self.client.post(self.url, {"action": "payment", "p-amount": "900", "p-paid_on": "02/09/2026",
                                               "p-method": "cash"})
        self.assertIn("amount", response.context["payment_form"].errors)
        page = self.client.get("/billing/payments/", {"date_from": "01/09/2026", "date_to": "30/09/2026"})
        self.assertEqual(page.context["total"], Decimal("700"))

    def test_only_the_front_desk(self):
        make_user("stock", "stock")
        self.client.login(username="stock", password=PASSWORD)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class BillTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        Service.objects.filter(name_en="CBCT").update(price=Decimal("1200"))
        Service.objects.filter(name_en="Consultation").update(price=Decimal("300"))
        self.cbct = Service.objects.get(name_en="CBCT")
        self.consult = Service.objects.get(name_en="Consultation")

    def post_bill(self, lines, **extra):
        data = {"patient_lookup": self.patient.file_number, "billed_on": "20/09/2026",
                "lines-TOTAL_FORMS": len(lines), "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 1,
                "lines-MAX_NUM_FORMS": 1000, "pay-method": "cash", **extra}
        for index, line in enumerate(lines):
            for key, value in line.items():
                data[f"lines-{index}-{key}"] = value
        return self.client.post("/billing/bills/new/", data)

    def test_bill_with_several_services_and_a_payment(self):
        from apps.billing.models import Bill

        page = self.client.get(f"/billing/bills/new/?patient={self.patient.pk}")
        self.assertEqual(sorted(s.name_en for s in page.context["quick_services"]), ["CBCT", "Consultation"])
        response = self.post_bill([
            {"service": self.consult.pk, "discount_percent": "100", "discount_reason": "First visit free"},
            {"service": self.cbct.pk, "teeth": "36 46"},
        ], **{"pay-amount": "1000"})
        bill = Bill.objects.get()
        self.assertRedirects(response, bill.get_absolute_url(), fetch_redirect_response=False)
        totals = bill.totals()
        self.assertEqual((totals["net"], totals["paid"], totals["left"]), (Decimal("1200"), Decimal("1000"), Decimal("200")))
        self.assertEqual(bill.charges.get(service=self.cbct).teeth, "46, 36")
        page = self.client.get(bill.get_absolute_url())
        self.assertContains(page, bill.number)
        # the rest is paid from the bill page; the list of unpaid bills is then empty
        from apps.billing.models import FawryMachine

        self.client.post(f"/billing/bills/{bill.pk}/pay/", {"pay-amount": "200", "pay-method": "fawry"})
        self.assertEqual(bill.totals()["left"], Decimal("200"))  # with two machines, the machine must be chosen
        second = FawryMachine.objects.order_by("pk")[1]
        self.client.post(f"/billing/bills/{bill.pk}/pay/", {"pay-amount": "200", "pay-method": "fawry",
                                                            "pay-fawry_machine": second.pk})
        self.assertEqual(bill.totals()["left"], Decimal("0"))
        self.assertEqual(bill.payments.get(method="fawry").fawry_move.machine, second)
        self.assertEqual(list(self.client.get("/billing/bills/?date_from=20/09/2026&date_to=20/09/2026&unpaid=on")
                              .context["rows"]), [])

    def test_a_bill_payment_pays_that_bill_first(self):
        from apps.billing.models import Bill

        Charge.objects.create(patient=self.patient, service=self.consult, price=Decimal("300"))  # older, unpaid
        self.post_bill([{"service": self.cbct.pk}], **{"pay-amount": "1200"})
        bill = Bill.objects.get()
        self.assertEqual(bill.totals()["left"], Decimal("0"))
        self.assertEqual(account(self.patient)["balance"], Decimal("300"))

    def test_a_discount_needs_a_reason(self):
        response = self.post_bill([{"service": self.cbct.pk, "discount_percent": "10"}])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["lines"].errors[0]["discount_reason"])


    def test_a_dentist_writes_the_bill_and_the_reception_collects(self):
        from apps.core.models import Notification, UserProfile
        from apps.core.testing import make_dentist

        dentist = make_dentist("doc", kind="fulltime")
        UserProfile.objects.update_or_create(user=User.objects.get(username="sec"), defaults={"branch": self.branch})
        self.client.login(username="doc", password=PASSWORD)
        page = self.client.get(f"/billing/bills/new/?patient={self.patient.pk}")
        self.assertIsNone(page.context["pay"])  # no payment part for the dentist
        self.assertContains(page, "Send the bill to the reception")
        response = self.post_bill([{"service": self.consult.pk}], **{"pay-amount": "300", "pay-method": "cash"})
        from apps.billing.models import Bill

        bill = Bill.objects.get()
        self.assertEqual((bill.source, bill.dentist, bill.payments.count()), (Bill.Source.DENTIST, dentist, 0))
        self.assertRedirects(response, bill.get_absolute_url())
        self.assertEqual(self.client.post(f"/billing/bills/{bill.pk}/pay/", {"pay-amount": "300"}).status_code, 403)
        note = Notification.objects.get(recipient__username="sec")
        self.assertIn(bill.patient.full_name, note.title)
        self.client.login(username="sec", password=PASSWORD)
        self.assertContains(self.client.get("/"), "فواتير الأطباء للتحصيل")
        from apps.billing.models import FawryMachine

        again = self.client.post(f"/billing/bills/{bill.pk}/pay/", {"pay-amount": "300", "pay-method": "fawry"})
        self.assertEqual(again.status_code, 200)  # two machines: which one? The form keeps Fawry chosen.
        self.assertIn("fawry_machine", again.context["pay_form"].errors)
        self.assertContains(again, 'value="fawry" autocomplete="off" checked')
        self.client.post(f"/billing/bills/{bill.pk}/pay/", {"pay-amount": "300", "pay-method": "fawry",
                                                          "pay-fawry_machine": FawryMachine.objects.first().pk})
        payment = bill.payments.get()
        self.assertEqual(payment.method, "fawry")
        receipt = self.client.get(payment.get_absolute_url())
        self.assertContains(receipt, "<td>ماكينة فوري")  # the reception reads Arabic: "Fawry POS machine"
        self.assertNotContains(receipt, "<td>كاش")
        self.assertNotContains(receipt, "نقدية")  # the Arabic title once said "cash receipt" for every payment


class FawryTests(TestCase):
    """Every move through the Fawry machine, its percentage, and the balance sheet."""

    def setUp(self):
        from apps.core.models import Branch, ClinicSettings

        self.branch = setup_clinic()
        self.clinic = Branch.objects.get(code="PVT")
        self.cic = Branch.objects.get(code="CIC")
        options = ClinicSettings.get()
        options.fawry_fee_percent = Decimal("2")
        options.save()
        self.patient = make_patient(self.branch)
        make_user("sec", "secretary")
        make_user("owner", "owner")

    def test_card_payments_come_in_by_themselves_with_the_fee(self):
        from apps.academy.models import Candidate, Course, Enrollment, Payment
        from apps.billing.models import FawryMove

        payment = PatientPayment.objects.create(patient=self.patient, amount=Decimal("1000"), method="fawry")
        move = payment.fawry_move
        self.assertEqual((move.kind, move.branch, move.amount, move.fee), ("collection", self.branch, Decimal("1000"), Decimal("20.00")))
        payment.amount = Decimal("500")
        payment.save()
        move.refresh_from_db()
        self.assertEqual((move.amount, move.fee), (Decimal("500"), Decimal("10.00")))
        payment.method = "cash"  # not through Fawry after all
        payment.save()
        self.assertFalse(FawryMove.objects.exists())
        course = Course.objects.create(branch=self.branch, name="Diploma", code="D-1", fee=Decimal("30000"))
        enrollment = Enrollment.objects.create(candidate=Candidate.objects.create(full_name="Dr. C", phone_primary="01001234567"),
                                               course=course, agreed_fee=Decimal("30000"))
        Payment.objects.create(enrollment=enrollment, amount=Decimal("5000"), method="fawry")
        self.assertEqual(FawryMove.objects.get().fee, Decimal("100.00"))

    def test_ledger_bills_bank_transfer_and_held_money(self):
        from apps.billing.fawry import held_at_fawry
        from apps.billing.models import FawryMove

        from apps.billing.models import FawryMachine

        PatientPayment.objects.create(patient=self.patient, amount=Decimal("1000"), method="fawry")  # 980 held
        machine = FawryMachine.default().pk
        self.client.login(username="sec", password=PASSWORD)
        today = timezone.localdate().strftime("%d/%m/%Y")
        response = self.client.post("/billing/fawry/new/", {
            "kind": "service", "branch": self.cic.pk, "moved_on": today, "amount": "200", "service": "electricity",
            "machine": machine,
        })
        self.assertEqual(response.status_code, 302)
        self.client.post("/billing/fawry/new/", {
            "kind": "service", "branch": self.clinic.pk, "moved_on": today, "amount": "100", "service": "mobile",
            "cash_received": "105", "description": "Recharge for a visitor", "machine": machine,
        })
        self.client.post("/billing/fawry/new/", {"kind": "settlement", "branch": self.branch.pk, "moved_on": today,
                                                 "amount": "500", "machine": machine})
        self.assertEqual(FawryMove.objects.count(), 4)
        self.assertEqual(held_at_fawry(), Decimal("180"))  # 980 - 200 - 100 - 500
        page = self.client.get("/billing/fawry/")
        # Round 13: the reception sees the moves she did herself, not the money held at Fawry.
        self.assertNotIn("held_now", page.context)
        self.assertEqual(len(page.context["moves"]), 3)
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/billing/fawry/")
        self.assertEqual(page.context["held_now"], Decimal("180"))
        self.assertEqual(page.context["moves"][0].running, Decimal("180"))
        self.assertEqual(len(page.context["moves"]), 4)
        self.client.login(username="sec", password=PASSWORD)
        # A bill paid through the machine needs to say which bill.
        response = self.client.post("/billing/fawry/new/", {"kind": "service", "branch": self.cic.pk, "moved_on": today,
                                                            "amount": "50"})
        self.assertIn("service", response.context["form"].errors)
        # The secretary cannot correct or delete; the owner can, but not a move made from a payment.
        self.assertEqual(self.client.post(f"/billing/fawry/{FawryMove.objects.last().pk}/delete/").status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        automatic = FawryMove.objects.get(patient_payment__isnull=False)
        self.client.post(f"/billing/fawry/{automatic.pk}/delete/")
        self.assertTrue(FawryMove.objects.filter(pk=automatic.pk).exists())
        self.client.post(f"/billing/fawry/{automatic.pk}/edit/", {"fee": "25"})
        automatic.refresh_from_db()
        self.assertEqual((automatic.fee, automatic.amount), (Decimal("25"), Decimal("1000")))

    def test_balance_sheet(self):
        from apps.billing.models import FawryMove
        from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier

        PatientPayment.objects.create(patient=self.patient, amount=Decimal("1000"), method="fawry")
        PatientPayment.objects.create(patient=self.patient, amount=Decimal("300"), method="cash")
        FawryMove.objects.create(branch=self.cic, kind="service", service="electricity", amount=Decimal("200"))
        FawryMove.objects.create(branch=self.clinic, kind="service", service="mobile", amount=Decimal("100"),
                                 cash_received=Decimal("105"))
        purchase = Purchase.objects.create(branch=self.branch, supplier=Supplier.objects.create(name="Dental Co"),
                                           payment_method="fawry")
        PurchaseItem.objects.create(purchase=purchase, category=PurchaseCategory.objects.filter(kind="dental").first(),
                                    description="Gloves", quantity=1, unit_price=Decimal("400"))
        from apps.billing.fawry import sync

        sync(purchase)  # the purchase form does this once the items are saved
        self.assertEqual(purchase.fawry_move.amount, Decimal("400"))
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/reports/balance/").context
        # Income: 1300 from the patient, 105 cash for the mobile recharge.
        self.assertEqual(page["income_total"], Decimal("1405"))
        # Costs: Fawry 20, bills 300 (the purchase is not counted twice), purchases 400.
        self.assertEqual(page["cost_total"], Decimal("720"))
        self.assertEqual(page["net_total"], Decimal("685"))
        self.assertEqual([b.code for b in page["columns"]], ["CIA", "PVT", "CIC"])
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/reports/balance/").status_code, 403)


class ReceiptReviewTests(TestCase):
    """Receipts are corrected, cancelled or refunded with a reason, and each day is closed and reviewed."""

    def setUp(self):
        from apps.core.models import UserProfile

        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        self.sec = make_user("sec", "secretary")
        UserProfile.objects.update_or_create(user=self.sec, defaults={"branch": self.branch})
        self.owner = make_user("owner", "owner")
        consult = Service.objects.get(name_en="Consultation")
        Charge.objects.create(patient=self.patient, service=consult, price=Decimal("1000"), branch=self.branch)
        self.payment = PatientPayment.objects.create(patient=self.patient, amount=Decimal("600"), method="cash",
                                                     branch=self.branch, created_by=self.sec)
        self.client.login(username="sec", password=PASSWORD)
        self.url = f"/billing/payments/{self.payment.pk}/change/"

    def test_a_correction_is_written_on_the_receipt(self):
        self.client.post(self.url, {"action": "correct", "c-amount": "600", "c-method": "instapay",
                                    "c-reference": "IP123", "c-reason": "The patient paid by InstaPay"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.method, "instapay")
        receipt = self.client.get(self.payment.get_absolute_url())
        self.assertContains(receipt, "The patient paid by InstaPay")
        self.assertContains(receipt, "600.00")

    def test_a_cancelled_receipt_counts_nowhere_but_stays_in_the_day(self):
        from apps.core.models import Notification

        self.client.post(self.url, {"action": "cancel", "x-reason": "Written twice"})
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_cancelled)
        self.assertEqual(account(self.patient)["paid"], Decimal("0"))
        self.assertFalse(PatientPayment.objects.exists())
        day = self.client.get("/billing/day/")
        self.assertEqual(day.context["summary"]["total"], Decimal("0"))
        self.assertEqual(len(day.context["summary"]["cancelled"]), 1)
        self.assertContains(day, self.payment.receipt_number)
        self.assertTrue(Notification.objects.filter(recipient=self.owner, level="warning").exists())  # the owner is told

    def test_a_refund_is_a_receipt_below_zero_up_to_what_was_paid(self):
        self.client.post(self.url, {"action": "refund", "r-amount": "900", "r-method": "cash", "r-reason": "x"})
        self.assertEqual(PatientPayment.objects.count(), 1)  # more than was paid: refused
        self.client.post(self.url, {"action": "refund", "r-amount": "200", "r-method": "cash",
                                    "r-reason": "The patient stopped the treatment"})
        back = PatientPayment.objects.get(refund_of=self.payment)
        self.assertEqual(back.amount, Decimal("-200"))
        self.assertEqual(account(self.patient)["paid"], Decimal("400"))
        self.assertEqual(self.client.get("/billing/day/").context["summary"]["total"], Decimal("400"))

    def test_the_reception_changes_only_the_receipts_of_today(self):
        from datetime import timedelta

        PatientPayment.objects.filter(pk=self.payment.pk).update(paid_on=timezone.localdate() - timedelta(days=2))
        self.client.post(self.url, {"action": "cancel", "x-reason": "late"})
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.is_cancelled)
        self.client.login(username="owner", password=PASSWORD)
        self.client.post(self.url, {"action": "cancel", "x-reason": "Wrong patient"})
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_cancelled)

    def test_the_day_is_closed_with_the_cash_counted_and_reviewed_by_the_owner(self):
        from apps.billing.models import DayClosing

        self.client.post("/billing/day/", {"action": "close", "cash_counted": "550"})
        closing = DayClosing.objects.get()
        self.assertEqual((closing.cash_expected, closing.difference, closing.total), (Decimal("600"), Decimal("-50"),
                                                                                      Decimal("600")))
        self.client.login(username="owner", password=PASSWORD)
        self.client.post("/billing/day/", {"action": "review", "review_notes": "50 missing: asked Mona"})
        closing.refresh_from_db()
        self.assertEqual(closing.reviewed_by, self.owner)
        month = self.client.get("/billing/month/")
        self.assertEqual(month.context["rows"][0]["closing"], closing)


class Round13ReceiptAndFawryTests(TestCase):
    """The receipt names the services it pays and carries the signatures; each person sees the Fawry moves they
    did; the owner changes Fawry's percentage on the Fawry page."""

    def setUp(self):
        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        self.sec = make_user("sec", "secretary", first_name="Mona")
        self.client.login(username="sec", password=PASSWORD)
        self.cbct = Service.objects.get(name_en="CBCT")
        self.consult = Service.objects.get(name_en="Consultation")

    def test_receipt_shows_each_service_it_pays_and_the_signatures(self):
        from apps.billing.models import paid_services
        from apps.core.models import UserProfile
        from apps.core.testing import make_dentist

        doctor = make_dentist("drmona", kind="fulltime", name="Dr. Mona")
        UserProfile.objects.update_or_create(user=doctor.user, defaults={"signature": "data:image/png;base64,QUJD"})
        UserProfile.objects.update_or_create(user=self.sec, defaults={"signature": "data:image/png;base64,REVG"})
        first = Charge.objects.create(patient=self.patient, service=self.consult, price=Decimal("300"), teeth="",
                                      dentist=doctor, charged_on=timezone.localdate())
        second = Charge.objects.create(patient=self.patient, service=self.cbct, price=Decimal("1000"), teeth="36",
                                       charged_on=timezone.localdate())
        one = PatientPayment.objects.create(patient=self.patient, amount=Decimal("500"), created_by=self.sec)
        two = PatientPayment.objects.create(patient=self.patient, amount=Decimal("400"), created_by=self.sec)
        # Paid oldest first, one receipt after the other.
        self.assertEqual([(c.pk, a) for c, a in paid_services(one)], [(first.pk, Decimal("300")), (second.pk, Decimal("200"))])
        self.assertEqual([(c.pk, a) for c, a in paid_services(two)], [(second.pk, Decimal("400"))])
        page = self.client.get(one.get_absolute_url())
        self.assertContains(page, str(self.cbct))
        self.assertContains(page, "(36)")
        self.assertContains(page, "data:image/png;base64,REVG")  # the secretary's signature
        self.assertContains(page, "data:image/png;base64,QUJD")  # the doctor of the first service
        advance = PatientPayment.objects.create(patient=make_patient(self.branch, nid="29001011234568",
                                                                     phone="01001234568"), amount=Decimal("100"))
        self.assertEqual(paid_services(advance), [])
        self.assertContains(self.client.get(advance.get_absolute_url()), "مدفوع مقدمًا")  # the secretary reads Arabic

    def test_each_person_sees_the_fawry_moves_they_did(self):
        from apps.billing.models import FawryMove

        other = make_user("sec2", "secretary")
        PatientPayment.objects.create(patient=self.patient, amount=Decimal("300"), method="fawry", created_by=self.sec)
        PatientPayment.objects.create(patient=self.patient, amount=Decimal("200"), method="fawry", created_by=other)
        self.assertEqual(set(FawryMove.objects.values_list("created_by__username", flat=True)), {"sec", "sec2"})
        page = self.client.get("/billing/fawry/")
        self.assertEqual([m.created_by for m in page.context["moves"]], [self.sec])
        self.assertNotIn("held_now", page.context)
        self.assertNotIn("person", page.context["form"].fields)
        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/billing/fawry/")
        self.assertEqual(len(page.context["moves"]), 2)
        page = self.client.get(f"/billing/fawry/?person={other.pk}")
        self.assertEqual([m.created_by for m in page.context["moves"]], [other])

    def test_the_owner_changes_the_fawry_percentage_on_the_fawry_page(self):
        from apps.core.models import ClinicSettings

        self.assertNotIn("percent_form", self.client.get("/billing/fawry/").context)
        self.assertEqual(self.client.post("/billing/fawry/percent/", {"percent": "3"}).status_code, 403)
        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)
        self.assertIn("percent_form", self.client.get("/billing/fawry/").context)
        self.client.post("/billing/fawry/percent/", {"percent": "1.75"})
        self.assertEqual(ClinicSettings.objects.get().fawry_fee_percent, Decimal("1.75"))
        self.client.post("/billing/fawry/percent/", {"percent": "50"})  # refused: not a real percentage
        self.assertEqual(ClinicSettings.objects.get().fawry_fee_percent, Decimal("1.75"))


class Round15MoneyTests(TestCase):
    """Round 15: giving money back by tapping the services, the owner's money, the small bill."""

    def setUp(self):
        from apps.billing.models import create_bill

        self.branch = setup_clinic()
        self.patient = make_patient(self.branch)
        self.secretary = make_user("sec", "secretary")
        self.owner = make_user("owner", "owner")
        self.client.login(username="sec", password=PASSWORD)
        self.cbct = Service.objects.get(name_en="CBCT")
        self.consult = Service.objects.get(name_en="Consultation")
        self.bill = create_bill(self.patient, [{"service": self.cbct, "price": Decimal("1000")},
                                               {"service": self.consult, "price": Decimal("300")}], self.secretary)
        self.cbct_line, self.consult_line = self.bill.charges.order_by("pk")
        self.paid = PatientPayment.objects.create(patient=self.patient, bill=self.bill, amount=Decimal("1300"),
                                                  created_by=self.secretary)

    def test_tap_the_service_to_give_back(self):
        from apps.billing.receipts import service_receipts

        url = f"/billing/patient/{self.patient.pk}/refund/"
        page = self.client.get(url)
        rows = {row["charge"].pk: row for row in page.context["rows"]}
        self.assertEqual(rows[self.cbct_line.pk]["paid"], Decimal("1000"))
        self.assertEqual(rows[self.cbct_line.pk]["receipts"], [(self.paid, Decimal("1000"))])  # the original
        # Nothing tapped: nothing given back.
        self.client.post(url, {"method": "cash", "reason": "x"})
        self.assertFalse(PatientPayment.objects.filter(amount__lt=0).exists())
        # The CBCT was not done: all of it back, and taken off his account.
        response = self.client.post(url, {f"take_{self.cbct_line.pk}": "1", f"amount_{self.cbct_line.pk}": "1000",
                                          "method": "cash", "reason": "CBCT machine broken", "not_done": "on"})
        back = PatientPayment.objects.get(amount__lt=0)
        self.assertRedirects(response, back.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((back.amount, back.refund_of, back.charge), (Decimal("-1000"), self.paid, self.cbct_line))
        self.cbct_line.refresh_from_db()
        self.assertEqual(self.cbct_line.net, Decimal("0"))
        self.assertEqual(account(self.patient)["balance"], Decimal("0"))
        self.assertEqual(service_receipts(self.patient)[self.cbct_line.pk]["paid"], Decimal("0"))
        # More than was paid is refused.
        self.client.post(url, {f"take_{self.consult_line.pk}": "1", f"amount_{self.consult_line.pk}": "500",
                               "method": "cash", "reason": "x"})
        self.assertEqual(PatientPayment.objects.filter(amount__lt=0).count(), 1)
        # Part of it, the service stays: he owes what was given back.
        self.client.post(url, {f"take_{self.consult_line.pk}": "1", f"amount_{self.consult_line.pk}": "100",
                               "method": "cash", "reason": "late"})
        self.assertEqual(account(self.patient)["balance"], Decimal("100"))

    def test_owner_money_counts_in_the_drawer_and_the_balance_sheet(self):
        from apps.billing.models import OwnerCash
        from apps.core.models import Notification

        response = self.client.post("/billing/owner-money/", {
            "place": "CIA", "direction": "in", "amount": "5000", "method": "cash", "moved_on": timezone.localdate()
            .strftime("%d/%m/%Y"), "reason": "to pay the implant supplier"})
        self.assertEqual(response.status_code, 302)
        move = OwnerCash.objects.get()
        self.assertEqual((move.branch, move.signed), (self.branch, Decimal("5000")))
        self.assertTrue(Notification.objects.filter(recipient=self.owner).exists())  # the reception wrote it
        day = self.client.get("/billing/day/").context["summary"]
        self.assertEqual(day["owner_cash"], Decimal("5000"))
        self.assertEqual(day["drawer"], Decimal("6300"))  # the cash receipt and the owner's cash
        self.client.logout()
        self.client.login(username="owner", password=PASSWORD)
        sheet = self.client.get("/reports/balance/").context
        self.assertEqual(sheet["owner_rows"][0]["total"], Decimal("5000"))
        self.assertEqual(sheet["after_owner_total"], sheet["net_total"] + Decimal("5000"))

    def test_the_bill_is_small_and_says_what_he_owes(self):
        from apps.billing.models import create_bill

        create_bill(self.patient, [{"service": self.consult, "price": Decimal("400")}], self.secretary)
        page = self.client.get(self.bill.get_absolute_url())
        self.assertContains(page, "receipt-80 bill-80")
        self.assertEqual(page.context["account"]["balance"], Decimal("400"))  # the other bill is owed too
        self.assertContains(self.client.get(self.bill.get_absolute_url() + "?a4=1"), "bill-print")
