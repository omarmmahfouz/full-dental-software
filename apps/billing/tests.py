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
        self.assertEqual(page.context["held_now"], Decimal("180"))
        self.assertEqual(page.context["moves"][0].running, Decimal("180"))
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
