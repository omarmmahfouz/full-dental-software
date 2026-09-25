from decimal import Decimal

from django.test import TestCase

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
